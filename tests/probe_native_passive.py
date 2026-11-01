"""Probe ORIGINAL Latent Passive Recall in isolation, with real local vectors.

This does not enable the feature in Luné. All facts are invented fixtures.
Requires a separately installed, unmodified Latent checkout and optional local
test packages: jieba, fastembed, tiktoken. Never calls a chat or paid API.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

REVISION = "835250d080c02d9553d3b96d9a2753773a4a0c3c"
MODEL = "BAAI/bge-small-zh-v1.5"

# Expectations are declared before running the model, not edited to fit scores.
FACT_TEXTS = [
    "她压力大时喜欢靠着窗听雨，什么都不做。",
    "上一次失眠，我们放了海浪声，她说终于慢慢放松了。",
    "她不喜欢太甜的饮料，常点无糖乌龙。",
    "她曾说，累的时候不需要建议，安静陪一会儿就好。",
    "她给猫买过纸箱，猫偏偏睡在快递包装里。",
    "她对那次被临时取消的约定失望，后来约好变动要提前说。",
    "她为第一次登台紧张，演出结束后说自己比想象中勇敢。",
    "她很喜欢深夜一起读几页书，不急着读完。",
    "她怕忘掉灵感，习惯把零碎的句子写进备忘录。",
    "她点过桂花酒酿，觉得香气柔和但不想喝烈酒。",
    "她赶完稿后想吃热汤面，觉得暖胃。",
    "她喜欢周末去海边看日落，安静坐一会儿。",
    "她曾在苏州生活，后来搬到了杭州。",
    "她目前住在杭州，习惯坐地铁通勤。",
    "她前天丢过一把银色钥匙，后来在包的夹层找到了。",
    "她喜欢用蓝色墨水写信，信封里会夹干花。",
]
CASES = [
    ("脑子绷了一整天，我现在不想再动了。", ["f01", "f04"]),
    ("今晚翻来覆去，怎么都睡不着。", ["f02"]),
    ("这杯喝着齁得慌，有没有清淡些的？", ["f03"]),
    ("今天不用替我想办法，让我歇会儿。", ["f01", "f04"]),
    ("小家伙又钻进刚拆的包装里了。", ["f05"]),
    ("怎么又到最后一刻才说来不了了。", ["f06"]),
    ("轮到我上场了，手心都在冒汗。", ["f07"]),
    ("睡前还想和你一起翻两页。", ["f08"]),
    ("刚闪过一个好句子，怕一会儿就没了。", ["f09"]),
    ("今晚想小酌一点，别太冲。", ["f10"]),
    ("写完了，肚子空得难受，想吃点暖乎的。", ["f11"]),
    ("想找个能看晚霞、听潮声的地方待一下午。", ["f12"]),
    ("土星的光环由什么组成？", []),
    ("帮我算一下十七乘二十九。", []),
    ("今天的汇率是多少？", []),
    ("嗯嗯", []),
    ("查一下Linux磁盘占用命令", []),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    actual = subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip()
    if actual != REVISION:
        raise SystemExit("Use the tested Latent revision; do not silently change the baseline")
    if subprocess.check_output(["git", "-C", str(args.source), "status", "--porcelain"], text=True).strip():
        raise SystemExit("Latent checkout has modifications")
    sys.path.insert(0, str(args.source / "src"))
    from embedding_provider import LocalProvider
    from memory_retrieval import MemoryIndex, _chunk_key
    from passive_facts import FactIndex, FactCooldown
    import passive_recall as pr
    from passive_recall_host import PassiveRecallAdapter, PassiveRecallConfig, request_token_upper_bound
    from mcp_server import MemoryServer
    import tiktoken

    provider = LocalProvider(MODEL)
    facts = [{"id": f"f{i+1:02}", "block": f"block-{i+1:02}", "fact": text,
              "event_date": "2026-01-02", "written": "2026-01-03", "tag": "life", "kind": "event"}
             for i, text in enumerate(FACT_TEXTS)]
    now = datetime(2026, 10, 24, 12, tzinfo=timezone.utc).timestamp()
    report = {"revision": actual, "date": "2026-10-24", "source_modified": False,
              "embedding_model": MODEL, "embedding_location": "local_cpu",
              "fact_floor": pr.FACT_FLOOR, "fact_floor_note": "native default; documented calibration is for voyage-3.5, not this model",
              "dataset": "invented fixtures, expectations fixed in script, not a representative benchmark",
              "packages": {p: version(p) for p in ("jieba", "fastembed", "onnxruntime", "numpy", "tiktoken")},
              "facts": facts, "chat_model_called": False, "lune_feature_enabled": False}
    checks = {}
    with tempfile.TemporaryDirectory(prefix="native-passive-probe-") as temp:
        root = Path(temp)
        os.environ["LATENT_PASSIVE_FACT_STATE_DIR"] = str(root / "state")
        os.environ["LATENT_PASSIVE_FACTS"] = ""
        file = root / "facts.jsonl"
        file.write_text("".join(json.dumps(f, ensure_ascii=False) + "\n" for f in facts), encoding="utf-8")
        before = hashlib.sha256(file.read_bytes()).hexdigest()
        started = time.perf_counter()
        fi = FactIndex(file, provider=provider)
        report["vector_build_seconds"] = round(time.perf_counter() - started, 4)
        if not fi.ready or fi.error:
            raise RuntimeError("Real embedding model did not initialize: " + str(fi.error))
        report["vector_dimension"] = len(fi.vectors[0])
        lookup = {_chunk_key(f["fact"]): f["id"] for f in facts}

        def index():
            idx = MemoryIndex()
            for fact in facts:
                idx.add(fact["fact"], {"record_id": fact["block"], "source": fact["block"] + ".md"})
            idx.build()
            idx.fixed_now = now
            return idx

        def service(cooldown=None, idx=None, fact_index=fi):
            return pr.PassiveRecallService(idx or index(), fact_index=fact_index, fact_cooldown=cooldown, assemble_candidates=True)

        def ask(svc, text, delivery="d1", scope="general", origin="main"):
            return svc.candidate({"userInput": text, "scope": scope, "origin": origin,
                                  "turn": {"sessionId": "probe", "turnId": delivery, "deliveryId": delivery}})

        def ids(result):
            return [lookup[r["recordId"]] for r in result.get("records", [])]

        quality = []
        for n, (query, expected) in enumerate(CASES):
            svc = service()
            started = time.perf_counter()
            result = ask(svc, query, "q" + str(n))
            got = ids(result)
            quality.append({"query": query, "expected_relevant": expected, "received": got,
                            "relevant_received": [x for x in got if x in expected],
                            "extra_received": [x for x in got if x not in expected],
                            "status": result["status"], "reason_codes": result["reasonCodes"],
                            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                            "native_payload": result.get("content", "")})
        report["quality"] = quality

        svc = service(FactCooldown(root / "cooldown.json"))
        first = ask(svc, CASES[1][0], "cool1")
        repeat = ask(svc, CASES[1][0], "cool2")
        restored = service(FactCooldown(root / "cooldown.json"))
        restart = ask(restored, CASES[1][0], "cool3")
        restored.index.fixed_now += 12 * 3600
        later = ask(restored, CASES[1][0], "cool4")
        checks["cooldown_repeat_empty"] = repeat["reasonCodes"] == ["fact_cooled"]
        checks["cooldown_survives_service_restart"] = restart["reasonCodes"] == ["fact_cooled"]
        checks["cooldown_expires_at_12h"] = ids(first) == ids(later) and bool(ids(later))
        checks["source_file_not_modified"] = hashlib.sha256(file.read_bytes()).hexdigest() == before

        svc = service()
        request = {"userInput": CASES[1][0], "turn": {"sessionId": "probe", "turnId": "same", "deliveryId": "same"}}
        one, two = svc.candidate(request), svc.candidate(copy.deepcopy(request))
        checks["same_delivery_idempotent"] = one == two
        checks["derived_not_injected"] = ask(service(), CASES[1][0], origin="derived")["reasonCodes"] == ["origin_derived"]
        dead = index()
        dead.retracted.add(1)
        checks["retracted_source_not_returned"] = "f02" not in ids(ask(service(idx=dead), CASES[1][0]))
        dead = index()
        dead.superseded.add(1)
        checks["superseded_source_not_returned"] = "f02" not in ids(ask(service(idx=dead), CASES[1][0]))
        checks["no_vectors_reported_explicitly"] = ask(service(fact_index=FactIndex(file)), CASES[1][0])["reasonCodes"] == ["fact_no_embedding"]

        def server():
            srv = MemoryServer(index=index(), enable_passive_recall=True)
            srv.passive = service(idx=srv.index)
            return srv

        srv = server()
        listed = srv.handle({"id": 1, "method": "tools/list"})["result"]["tools"]
        message = {"id": 2, "method": "tools/call", "params": {"name": "latent_passive_recall", "arguments": request}}
        denied = srv.handle(message)
        allowed = srv.handle(message, hidden_ok=True)
        checks["hidden_not_listed_for_model"] = "latent_passive_recall" not in [t["name"] for t in listed]
        checks["ordinary_caller_denied"] = denied.get("error", {}).get("code") == -32601
        checks["native_hidden_entry_returns_ready"] = allowed["result"]["structuredContent"]["status"] == "ready"

        encoding = tiktoken.get_encoding("o200k_base")
        def count(message):
            # A reproducible tokenizer-specific probe, not a promise about Claude or billing.
            return len(encoding.encode(json.dumps(message, ensure_ascii=False, separators=(",", ":")))) + 4
        report["host_probes"] = []
        for counter, label in ((None, "native_utf8_byte_upper_bound"), (count, "o200k_base_probe_not_billing")):
            srv = server()
            def fetch(req, timeout):
                return srv.handle({"id": 3, "method": "tools/call", "params": {"name": "latent_passive_recall", "arguments": req}}, hidden_ok=True)["result"]["structuredContent"]
            history = [{"role": "user", "content": CASES[1][0]}]
            kwargs = {"token_counter": counter, "token_counter_name": label} if counter else {}
            adapter = PassiveRecallAdapter(PassiveRecallConfig(True, "temporary"), fetch=fetch, **kwargs)
            state = adapter.begin_turn(history, session_id="probe", turn_id="host", delivery_id="host", user_input=CASES[1][0], scope="general")
            projection = adapter.messages_for_request(history)
            report["host_probes"].append({"counter": label, "state": state, "elapsed_ms": adapter.turn.get("elapsed_ms"),
                "injected": len(projection) > len(history), "source_history_unchanged": len(history) == 1,
                "utf8_byte_upper_bound": request_token_upper_bound({"role": "system", "content": adapter.turn.get("message", {}).get("content", "")}) if state == "ready" else None,
                "request_projection": projection})
        checks["temporary_mode_does_not_write_history"] = all(r["source_history_unchanged"] for r in report["host_probes"])
        report["checks"] = checks
        report["mechanical_checks_passed"] = sum(checks.values())
        report["mechanical_checks_total"] = len(checks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(args.output), "checks": checks,
                      "host_probes": [{k:v for k,v in p.items() if k != "request_projection"} for p in report["host_probes"]],
                      "quality": [{k:v for k,v in q.items() if k != "native_payload"} for q in report["quality"]]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
