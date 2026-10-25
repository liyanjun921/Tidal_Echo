"""Host the separately installed, unmodified Latent product API on private corpora.

SQLite records are read-only sources. Native writes have one canonical Markdown
corpus per room. No public repository contains third-party code or private data.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import time

_states = {}


def governance(server, records, roots, directory):
    """Merge read-side ledgers; keep each canonical room ledger writable only there."""
    from latent_passive import _atomic
    supersessions, retractions = {}, {}
    for root in reversed(roots):
        file = root / ".supersessions.json"
        if file.is_file():
            raw = json.loads(file.read_text(encoding="utf-8"))
            supersessions.update(raw.get("records", raw))
        file = root / ".retractions.json"
        if file.is_file():
            retractions.update(json.loads(file.read_text(encoding="utf-8")))
    for row in records:
        rid = hashlib.sha256(("lune:" + row["id"]).encode()).hexdigest()[:16]
        old, new = row.get("supersedes"), row.get("superseded_by")
        if old or new:
            supersessions[rid] = {"status": row["status"],
                "supersedes": hashlib.sha256(("lune:" + old).encode()).hexdigest()[:16] if old else None,
                "superseded_by": hashlib.sha256(("lune:" + new).encode()).hexdigest()[:16] if new else None}
    sp, rp = directory / ".effective-supersessions.json", directory / ".effective-retractions.json"
    _atomic(sp, json.dumps(supersessions, ensure_ascii=False))
    _atomic(rp, json.dumps(retractions, ensure_ascii=False))
    server.index.load_supersessions(sp)
    server.index.load_retractions(rp)
    for i, meta in enumerate(server.index.meta):
        if meta.get("lune_legacy"):
            row = next(r for r in records if meta["source"].endswith("/" + r["id"]))
            if row["status"] == "superseded":
                meta["status"] = "superseded"
                server.index.superseded.add(i)


@contextmanager
def locked(root):
    import fcntl
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / ".workspace.lock").open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def fingerprint(paths):
    h = hashlib.sha256()
    for root in paths:
        for p in sorted(root.rglob("*")):
            if p.is_file() and not p.is_symlink() and ".cleanup-trash" not in p.parts:
                h.update(str(p).encode())
                h.update(str((p.stat().st_mtime_ns, p.stat().st_size)).encode())
    return h.hexdigest()


def get_state(p):
    from memory_retrieval import load_corpus
    from mcp_server import MemoryServer, diagnose, doctor_json
    from session_thread import ThreadStore
    from time_context import TimeContext
    from admin_api import AdminAPI
    root, view = Path(p["full_root"]), p["view"]
    if view not in {"gpt", "claude", "shared", "group"}:
        raise ValueError("invalid_view")
    directory = root / view
    corpus = directory / "memory"
    corpus.mkdir(parents=True, exist_ok=True, mode=0o700)
    shared = root / "shared" / "memory"
    shared.mkdir(parents=True, exist_ok=True, mode=0o700)
    roots = [corpus] + ([shared] if view != "shared" else [])
    compiled = directory / "initialization" / "memory"
    if compiled.is_dir() and (directory / "initialization" / ".lune-shipped").is_file():
        roots.append(compiled)
    route = p.get("embedding_route", "local")
    provider = None
    if route == "local":
        from latent_passive import native_provider
        provider = native_provider(Path(p["model_cache"]))
    elif route == "cloud":
        if os.environ.get("LUNE_LATENT_CLOUD_CONSENT") != "1":
            raise ValueError("cloud_not_consented")
        from embedding_provider import resolve_provider
        provider = resolve_provider("cloud")
    elif route != "zero-dep":
        raise ValueError("invalid_route")
    records = p.get("records", [])
    signature = fingerprint(roots) + hashlib.sha256(json.dumps(
        [(r["id"], r["version"], r["status"]) for r in records]).encode()).hexdigest() + route
    key = str(directory)
    if key in _states and _states[key]["signature"] == signature:
        return _states[key]
    tc = TimeContext("Asia/Shanghai")
    def loader():
        index = load_corpus(roots, embed=provider is not None, provider=provider,
                            cache_path=directory / ".embedding-cache.json" if provider else None)
        for r in records:
            # Stable source identity; native tools cannot mutate this source.
            rid = hashlib.sha256(("lune:" + r["id"]).encode()).hexdigest()[:16]
            index.add(r["title"] + "\n" + r["content"] + "\n当下状态：" + r["current_state"],
                      {"source": "LuneSQLite/" + r["scope"] + "/" + r["id"], "record_id": rid,
                       "record_id_aliases": [rid], "layer": "timeline", "heading": r["title"],
                       "timestamp": r["timestamp"], "local_date": r["written_date"],
                       "status": r["status"], "lune_legacy": True})
            if r["status"] == "superseded":
                index.superseded.add(len(index.chunks) - 1)
        return index.build()
    server = MemoryServer(index=loader(), corpus_dir=corpus,
        thread_store=ThreadStore(directory / "threads.jsonl"),
        weights_path=corpus / ".weights.json", retractions_path=corpus / ".retractions.json",
        supersessions_path=corpus / ".supersessions.json", entities_path=corpus / ".entities.json",
        source_dirs=roots, loader=loader, time_context=tc, enable_passive_recall=True)
    server.enable_notes()
    governance(server, records, roots, directory)
    def doctor():
        return doctor_json(diagnose(corpus, threads_path=directory / "threads.jsonl",
                                    embed=provider is not None, time_context=tc))
    state = {"server": server, "signature": signature, "corpus": corpus, "directory": directory,
             "admin": AdminAPI(server, persona_path=directory / "persona.md", diagnose=doctor,
                               fact_path=corpus / "事实库"), "doctor": doctor,
             "deliveries": {}}
    _states[key] = state
    return state


def guard_write(state, name, args):
    """A private model may read shared sources but only write its own corpus."""
    s, corpus = state["server"], state["corpus"].resolve()
    ids = {str(args.get(k) or "") for k in ("recordId", "supersedes", "by")}
    quote = args.get("quote") if name == "latent_correct" else None
    for i, meta in enumerate(s.index.meta):
        if meta.get("record_id") not in ids and not (quote and quote in s.index.chunks[i]):
            continue
        source = str(s.index.paths[i] or "")
        if meta.get("lune_legacy"):
            raise PermissionError("这是 Luné 原有记忆，请在原记忆编辑器中修改，不能另写一份覆盖。")
        try:
            Path(source).resolve().relative_to(corpus)
        except ValueError:
            raise PermissionError("共享或其他房间的来源只能读取，不能从本房间修改。") from None


def call(state, msg, hidden=False):
    name = (msg.get("params") or {}).get("name", "")
    if name in {"latent_correct", "latent_supersede", "latent_cleanup", "latent_append"}:
        guard_write(state, name, (msg.get("params") or {}).get("arguments") or {})
    response = state["server"].handle(msg, hidden_ok=hidden)
    if name in {"latent_correct", "latent_supersede", "latent_cleanup", "latent_append"}:
        # The effective read index includes shared governance; never persist its
        # projected entries as another room's independently editable truth.
        from latent_passive import _atomic
        index = state["server"].index
        owned = set()
        for i, meta in enumerate(index.meta):
            path = index.paths[i]
            if path and Path(path).resolve().is_relative_to(state["corpus"].resolve()):
                owned.update(meta.get("record_id_aliases", [meta.get("record_id")]))
        for filename, raw in ((".supersessions.json", index.supersession_log), (".retractions.json", index.retraction_log)):
            file = state["corpus"] / filename
            if file.is_file():
                _atomic(file, json.dumps({k: v for k, v in raw.items() if k in owned}, ensure_ascii=False))
    # Native writes rebuild/update their index; recreate from disk on the next call.
    if name not in {"latent_search", "latent_session_start", "latent_passive_recall", ""}:
        state["signature"] = "changed"
    return response


def dispatch(p):
    from passive_recall_host import PassiveRecallAdapter, PassiveRecallConfig
    root = Path(p["full_root"])
    with locked(root):
        os.environ["LATENT_PASSIVE_FACT_STATE_DIR"] = str(root / p["view"] / "fact-state")
        os.environ["LATENT_SUPERSEDE_HINT_LOG"] = str(root / p["view"] / "supersede-hints.jsonl")
        state = get_state(p)
        action = p["action"]
        if action == "rpc":
            try:
                return {"rpc": call(state, p["message"])}
            except PermissionError as exc:
                return {"rpc": {"jsonrpc": "2.0", "id": p["message"].get("id"), "result": {
                    "isError": True, "content": [{"type": "text", "text": str(exc)}]}}}
        if action == "admin":
            api = state["admin"]
            code, body = (api.handle_post(p["path"], p.get("data", {})) if p.get("method") == "POST"
                          else api.handle(p["path"], p.get("query", {})))
            return {"status": code, "body": body}
        if action == "doctor":
            return {"doctor": state["doctor"]()}
        if action == "checkpoint":
            latest = state["server"].thread_store.latest()
            return {"rpc": call(state, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "latent_thread_close", "arguments": {
                    "window": latest.window + 1 if latest else 1, "topics": p.get("topics", []),
                    "current_state": p["current_state"], "unresolvedOps": [{"action": "none"}]}}})}
        if action == "context":
            server = state["server"]
            opening = ""
            if p.get("opening"):
                if p.get("tail"):
                    from session_thread import auto_close_thread
                    latest = server.thread_store.latest()
                    if latest is None or latest.ended_at < p["tail_end"]:
                        server.thread_store.append(auto_close_thread(latest.window + 1 if latest else 1,
                            p["tail_start"], p["tail"], now=p["tail_end"]))
                result = call(state, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "latent_session_start", "arguments": {}}})
                opening = "\n".join(c.get("text", "") for c in result.get("result", {}).get("content", []))
            delivery = p["delivery_id"]
            if delivery in state["deliveries"]:
                passive = state["deliveries"][delivery]
            else:
                outcome = {}
                def fetch(request, timeout):
                    request["origin"] = "main"
                    value = call(state, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "latent_passive_recall", "arguments": request}}, hidden=True)
                    if value.get("error") or value["result"].get("isError"):
                        raise RuntimeError("native_passive_failed")
                    outcome.update(value["result"]["structuredContent"])
                    return outcome
                history = [{"role": "user", "content": p["query"]}]
                host = PassiveRecallAdapter(PassiveRecallConfig(bool(p.get("auto_recall")), "temporary"), fetch=fetch)
                status = host.begin_turn(history, session_id=p["session_id"], turn_id=delivery,
                    delivery_id=delivery, user_input=p["query"], scope=p["view"])
                messages = host.messages_for_request(history)
                passive = {"text": messages[-1]["content"] if len(messages) > 1 else "",
                           "status": status, "reason_codes": outcome.get("reasonCodes", [])}
                state["deliveries"][delivery] = passive
                if len(state["deliveries"]) > 256:
                    state["deliveries"].pop(next(iter(state["deliveries"])))
            tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
            persona = state["directory"] / "persona.md"
            return {"text": opening, "passive": passive, "tools": tools,
                    "instructions": server.instructions,
                    "persona": persona.read_text(encoding="utf-8") if persona.is_file() else "",
                    "native_records": sum(not m.get("lune_legacy") for m in server.index.meta)}
        raise ValueError("unknown_full_action")
