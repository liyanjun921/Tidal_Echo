"""Luné host adapter for the unmodified Latent Passive Recall implementation.

The parent supplies an authorized snapshot; only private derived caches persist.
No chat API, cloud embedding or model-visible hidden tool is exposed here.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

MODEL = "BAAI/bge-small-zh-v1.5"
_provider = None
_views = {}


def facts_from_records(records):
    """Source excerpts, not invented or model-rewritten facts; long prose stays searchable."""
    out = []
    for row in records:
        # Keep complete sentences. Never cut a long sentence into unsupported fragments.
        for sentence in re.findall(r"[^。！？\n]+(?:[。！？]+|$)", row["content"]):
            sentence = sentence.strip()
            if not 8 <= len(sentence) <= 120:
                continue
            out.append({"id": row["id"] + ":" + hashlib.sha256(sentence.encode()).hexdigest()[:12],
                        "block": row["id"], "fact": sentence, "event_date": None,
                        "written": row["written_date"], "tag": "life", "kind": "event"})
    if len(out) > 10000:
        raise ValueError("fact_limit")
    return out


def _atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".facts-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def native_provider(cache):
    global _provider
    if _provider is None:
        from embedding_provider import LocalProvider
        from fastembed import TextEmbedding
        # Configure the native provider's underlying backend for offline runtime.
        provider = LocalProvider(MODEL)
        provider._embedder = TextEmbedding(MODEL, cache_dir=str(cache), local_files_only=True, threads=2)
        _provider = provider
    return _provider


def recall(payload, index):
    from mcp_server import MemoryServer
    from passive_facts import FactIndex, FactCooldown, FactVectorCache
    from passive_recall import PassiveRecallService
    from passive_recall_host import PassiveRecallAdapter, PassiveRecallConfig
    import tiktoken

    root = Path(payload["private_state"])
    cache = Path(payload["model_cache"])
    view = payload["view"]
    if view not in {"gpt", "claude", "group", "shared"}:
        raise ValueError("scope_invalid")
    provider = native_provider(cache)
    if payload["operation"] == "passive_check":
        dimension = len(provider.embed(["运行检查"])[0])
        return {"text": "", "matches": [], "passive": {"native": True, "status": "checked", "model": MODEL,
                 "mode": "temporary", "dimension": dimension, "injected": False, "fact_count": 0}}
    facts = facts_from_records(payload["records"])
    signature = hashlib.sha256(json.dumps([(r["id"], r["version"], r["status"]) for r in payload["records"]]).encode()).hexdigest()
    key = str(root / view)
    state = _views.get(key)
    if state is None or state["signature"] != signature:
        directory = root / view
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        file = directory / "facts.jsonl"
        _atomic(file, "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in facts))
        fact_index = FactIndex(file, provider=provider, cache=FactVectorCache(str(directory / "vectors"), provider.id))
        if not fact_index.ready or fact_index.error:
            raise RuntimeError("fact_index_failed")
        native = PassiveRecallService(index, fact_index=fact_index,
                    fact_cooldown=FactCooldown(directory / "cooldown.json"), assemble_candidates=True)
        server = MemoryServer(index=index)
        server.passive = native
        state = {"signature": signature, "server": server, "fact_index": fact_index, "deliveries": {}}
        _views[key] = state
    else:
        state["server"].index = index
        state["server"].passive.set_index(index)
    delivery = payload["delivery_id"] + ":" + signature[:12]
    if delivery in state["deliveries"]:
        return state["deliveries"][delivery]
    server = state["server"]
    outcome = {}
    def fetch(request, timeout):
        request["origin"] = "main"
        result = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "latent_passive_recall", "arguments": request}}, hidden_ok=True)
        if result.get("error") or result["result"].get("isError"):
            raise RuntimeError("native_hidden_entry_failed")
        outcome.update(result["result"]["structuredContent"])
        return outcome
    encoding = tiktoken.get_encoding("o200k_base")
    def count(message):
        # Named reference encoding for a bounded injection, never a billing estimate.
        return len(encoding.encode(json.dumps(message, ensure_ascii=False, separators=(",", ":")))) + 4
    host = PassiveRecallAdapter(PassiveRecallConfig(True, "temporary"), fetch=fetch,
                 timeout_seconds=2.0, token_counter=count, token_counter_name="lune-o200k-reference-v1")
    history = [{"role": "user", "content": payload["query"]}]
    began = time.perf_counter()
    status = host.begin_turn(history, session_id=payload["session_id"], turn_id=delivery,
                   delivery_id=delivery, user_input=payload["query"], scope=view)
    projection = host.messages_for_request(history)
    injected = len(projection) > len(history)
    text = projection[-1]["content"] if injected else ""
    matches, fact_ids = [], []
    if injected:
        for record in outcome.get("records", []):
            fact_ids.append(record["recordId"])
            row = state["fact_index"].row(record["recordId"])
            if row and row["meta"]["block"] not in {m["id"] for m in matches}:
                matches.append({"id": row["meta"]["block"], "score": 0.0})
    result = {"text": text, "matches": matches, "passive": {"native": True,
            "entry": "latent_passive_recall", "status": status, "mode": "temporary", "model": MODEL,
            "injected": injected, "fact_count": len(fact_ids), "fact_ids": fact_ids,
            "eligible_facts": len(facts), "reason_codes": outcome.get("reasonCodes", []),
            "elapsed_ms": round((time.perf_counter() - began) * 1000, 2)}}
    state["deliveries"][delivery] = result
    if len(state["deliveries"]) > 256:
        state["deliveries"].pop(next(iter(state["deliveries"])))
    return result
