"""Bounded private worker using an independently installed Latent engine.

Receives only a pre-authorized snapshot on stdin, never a database path or keys.
No model API, embedding service, native write tools or hidden hooks are enabled.
"""
import json
from pathlib import Path
import sys
import time


def run(payload):
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
    elif query and payload.get("auto_recall"):
        # Native read-only candidate path; ordinary automatic checks do not boost weights.
        results = index.retrieve_candidates(query, topN=4)
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
    return {"matches": rows, "text": format_recall_block(results, time_context=tc) or "",
            "opening": opening, "weights": {m["record_id"]: index.weights[i] for i, m in enumerate(index.meta)}}


if __name__ == "__main__":
    sys.path.insert(0, str(Path(sys.argv[1]) / "src"))
    try:
        payload = json.load(sys.stdin)
        print(json.dumps(run(payload), ensure_ascii=False))
    except Exception:
        # Never echo private content, source errors, or request arguments.
        print(json.dumps({"error": "Latent 运行失败，请检查独立安装的固定版本"}, ensure_ascii=False))
        sys.exit(1)
