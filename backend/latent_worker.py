"""Bounded private worker using an independently installed Latent engine.

Receives only a pre-authorized snapshot on stdin, never a database path or keys.
Native Passive Recall is host-only; embeddings run locally, with no chat API.
"""
import json
from pathlib import Path
import sys
import time


def run(payload):
    if payload.get('operation') == 'embed':
        from latent_passive import native_provider
        return {'vectors': [[float(v) for v in row] for row in native_provider(payload['model_cache']).embed(payload['input'])]}
    if payload.get("operation") == "full":
        from latent_full_worker import dispatch
        return dispatch(payload)
    from memory_retrieval import MemoryIndex, has_history_intent
    from session_recall import SessionRecall, format_recall_block
    from session_thread import ThreadStore, auto_close_thread
    from time_context import TimeContext

    index = MemoryIndex(embed=False)
    tc = TimeContext.default()
    query = payload.get("query", "")
    historical = has_history_intent(query)
    for row in payload["records"]:
        text = row["title"] + "\n" + row["content"] + "\n当下状态：" + row["current_state"]
        index.add(text, {"record_id": row["id"], "record_id_aliases": [row["id"]],
                        "source": "Luné/" + row["scope"] + "/" + row["id"],
                        "heading": row["title"], "layer": "timeline",
                        "timestamp": row["timestamp"], "local_date": tc.local_date(row["timestamp"]),
                        "status": row["status"], "supersedes": row.get("supersedes"),
                        "superseded_by": row.get("superseded_by")})
        index.weights[-1] = row["weight"]
        if row["status"] == "superseded":
            index.superseded.add(len(index.chunks) - 1)
    index.build()
    if payload["operation"] == "search":
        results = index.retrieve(query, topN=payload.get("top_n", 5), include_superseded=historical)
        if historical:
            # Complete only explicit links inside this already-authorized snapshot.
            by_id = {meta["record_id"]: i for i, meta in enumerate(index.meta)}
            pending, seen = [r["meta"]["record_id"] for r in results], set()
            while pending:
                mid = pending.pop()
                if mid in seen or mid not in by_id:
                    continue
                seen.add(mid)
                meta = index.meta[by_id[mid]]
                pending.extend([meta.get("supersedes"), meta.get("superseded_by")])
            existing = {r["meta"]["record_id"] for r in results}
            results += [{"id": by_id[mid], "text": index.chunks[by_id[mid]], "meta": index.meta[by_id[mid]], "score": 0.0} for mid in seen - existing]
            results.sort(key=lambda r: (r["meta"].get("timestamp", 0), r["meta"]["record_id"]))
            results = results[:50]
    else:
        results = []
    rows = [{"id": r["meta"]["record_id"], "text": r["text"], "status": r["meta"]["status"],
             "score": r["score"]} for r in results]
    opening = ""
    if payload.get("opening"):
        threads = ThreadStore()
        tail = payload.get("tail", [])
        if tail:
            threads.append(auto_close_thread(1, payload.get("tail_started", time.time()),
                                             tail, now=payload.get("tail_ended", time.time())))
        opening = SessionRecall(index, topN=2, thread_store=threads, time_context=tc).on_session_start() or ""
    output = {"matches": rows, "text": format_recall_block(results, time_context=tc) or "",
              "opening": opening, "weights": {m["record_id"]: index.weights[i] for i, m in enumerate(index.meta)}}
    if payload["operation"] == "passive_check" or (payload["operation"] == "context" and payload.get("auto_recall")):
        from latent_passive import recall
        output.update(recall(payload, index))
    return output


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(sys.argv[1]) / "src"))
    def respond(payload):
        try:
            value = run(payload)
        except Exception:
            value = {"error": "Latent 运行失败，请检查固定源码、本地向量安装与私人目录"}
        sys.stdout.buffer.write(json.dumps(value, ensure_ascii=False).encode() + b"\n")
        sys.stdout.buffer.flush()
    if "--serve" in sys.argv:
        for line in sys.stdin.buffer:
            respond(json.loads(line.decode("utf-8")))
    else:
        respond(json.loads(sys.stdin.buffer.read().decode("utf-8")))
