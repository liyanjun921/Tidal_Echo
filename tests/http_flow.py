"""Real HTTP flow against isolated run_e2e.py services; synthetic credentials only."""
import time
import uuid
import httpx
import os
import sqlite3
from datetime import datetime, timedelta, timezone

with httpx.Client(base_url="http://127.0.0.1:8089/relay", headers={"Authorization": "Bearer fixture-owner-secret"}, trust_env=False, timeout=30) as c:
    def post(path, body):
        r = c.post(path, json=body)
        r.raise_for_status()
        return r.json()

    def send(room, text, attachments=None):
        result = post(f"/lune/rooms/{room}/send", {"text": text, "nonce": uuid.uuid4().hex, "attachments": attachments or []})
        for _ in range(150):
            data = c.get(f"/lune/rooms/{room}/messages").json()
            run = next((r for r in data["runs"] if r["id"] == result["run"]["id"]), None)
            if run and run["state"] not in {"pending", "running"}:
                assert run["state"] == "completed", run
                return data
            time.sleep(.1)
        raise AssertionError("run did not finish")

    for name in ("gpt", "claude"):
        post("/app/loop/agents", {"agent": name, "url": "http://127.0.0.1:8766/v1", "model": "fixture-" + name, "key": "not-a-real-key-" + name, "protocol": "openai" if name == "gpt" else "anthropic"})
    post("/app/loop/mcp", {"name": "fixture", "transport": "http", "url": "http://127.0.0.1:8767/mcp", "enabled": True})
    for _ in range(60):
        if any(s["status"] == "online" for s in c.get("/app/loop/mcp").json()["servers"]):
            break
        time.sleep(.1)
    else:
        raise AssertionError("MCP did not connect")
    private = send("gpt", "PRIVATE_UI_MARKER")
    assert any("TEST_GPT" in m["text"] for m in private["messages"])
    post("/lune/memories", {"scope": "gpt", "title": "private", "content": "PRIVATE_UI_MARKER"})
    post("/lune/workspace", {"kind": "whisper", "scope": "gpt", "title": "private", "content": "PRIVATE_UI_MARKER"})
    group = send("group", "GROUP_UI_MARKER")
    assert any("TEST_CLAUDE" in m["text"] for m in group["messages"])
    upload = c.post("/app/upload?name=note.txt", content=b"ATTACHMENT_BODY_MARKER", headers={"Content-Type": "text/plain"})
    upload.raise_for_status()
    att = upload.json()
    att = att.get("attachment", att.get("upload", att))
    send("group", "@GPT Read attachment", [att])
    send("group", "@GPT TOOL_UI_MARKER")
    send("group", "@GPT WORKSPACE_TRIGGER")
    records = c.get("/lune/workspace").json()["items"]
    saved = next(x for x in records if x["title"] == "HTTP_TOOL_SAVED")
    assert saved["scope"] == "group" and saved["author"] == "gpt", saved
    assert any(x["title"] == "HTTP_TOOL_SAVED" for x in c.get("/lune/export").json()["workspace"])
    if c.get("/lune/memory/status").json()["passive"]["assets_ready"]:
        assert post("/lune/memory/check", {})["ok"]
        send("gpt", "记住：我喜欢蓝色鸢尾。 MEMORY_WRITE_TRIGGER")
        memories = c.get("/lune/memories").json()["memories"]
        remembered = next(m for m in memories if m["title"] == "HTTP_MEMORY_SAVED")
        assert remembered["scope"] == "gpt" and remembered["source_message_id"]
        # Original Passive Recall intentionally skips facts written today.
        # Age only this isolated synthetic fixture to represent a past memory.
        with sqlite3.connect(os.environ["RELAY_DB"]) as db:
            at = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
            db.execute("UPDATE lune_memories SET created_at=?,updated_at=? WHERE id=?", (at, at, remembered["id"]))
        assert any(m["id"] == remembered["id"] for m in post("/lune/memory/search", {"view": "gpt", "query": "蓝色鸢尾"})["matches"])
        assert not any(m["id"] == remembered["id"] for m in post("/lune/memory/search", {"view": "group", "query": "蓝色鸢尾"})["matches"])
        send("gpt", "蓝色鸢尾")
        response = c.get("/lune/rooms/gpt/messages").json()["messages"]
        latest = next(m for m in reversed(response) if m["from"] == "ai" and m["kind"] == "reply")
        assert latest["meta"]["api"]["memory"]["engine"] == "latent"
        assert remembered["id"] in latest["meta"]["api"]["memory"]["ids"]
        trace = latest["meta"]["api"]["memory"]["passive"]
        assert trace["native"] and trace["injected"] and trace["entry"] == "latent_passive_recall", trace
        assert trace["mode"] == "temporary" and trace["fact_count"] >= 1
        send("gpt", "蓝色鸢尾")
        response = c.get("/lune/rooms/gpt/messages").json()["messages"]
        latest = next(m for m in reversed(response) if m["from"] == "ai" and m["kind"] == "reply")
        assert latest["meta"]["api"]["memory"]["passive"]["reason_codes"] == ["fact_cooled"]
        assert not any("〔历史证据〕" in m["text"] for m in c.get("/lune/export").json()["messages"])
        print("Native Passive Recall HTTP PASS: model tool → source-backed write → original hidden entry → actual provider request → next-turn cooldown; group isolated")
    for provider, model in (("minimax", "speech-02-hd"), ("elevenlabs", "eleven_multilingual_v2")):
        config = c.get("/lune/speech").json()
        r = c.patch("/lune/speech", json={"provider": provider, "version": config["version"], "providers": {provider: {"key": "synthetic-voice-key", "voice_id": "fixture_voice", "model": model, "base_url": "http://127.0.0.1:8766"}}})
        r.raise_for_status()
        assert "synthetic-voice-key" not in r.text
        result = c.post("/app/tts", json={"text": "测试朗读"})
        result.raise_for_status()
        assert result.content == ("ID3synthetic-" + provider).encode()
    if os.environ.get("LUNE_LATENT_SOURCE"):
        import json
        def native_job(kind, data=None):
            jid = post('/lune/native/gpt/jobs/'+kind, data or {})['id']
            for _ in range(400):
                jobs = c.get('/lune/native/status').json()['jobs']
                job = next(j for j in jobs if j['id']==jid)
                if job['state'] not in {'queued','running'}:
                    assert job['state']=='done', job
                    return json.loads(job['result'])
                time.sleep(.1)
            raise AssertionError('native job timeout')
        archived = native_job('flush')
        assert archived['status']=='flushed' and archived['batches'], archived
        assert archived['cursor_epoch']>0
        tools = post('/lune/native/gpt/mcp', {'jsonrpc':'2.0','id':1,'method':'tools/list'})['result']['tools']
        assert len(tools)==10 and all(t['name']!='latent_passive_recall' for t in tools)
        search = post('/lune/native/gpt/mcp', {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'latent_search','arguments':{'query':'蓝色鸢尾'}}})
        assert not search['result'].get('isError'), search
        imported = native_job('import', {'name':'history.md','content':'## 2026-10-20\n用户：NATIVE_IMPORT_MARKER 在海边看到了蓝色风筝。\n助手：我们记下了那只风筝。\n当下状态：这件事已经结束。'})
        assert imported['entries']>0
        backed = native_job('backup')
        backup = c.get(backed['download']);backup.raise_for_status();assert backup.content[:2]==b'PK'
        checked = native_job('initialize', {'step':'inspect','persona':'这是用户自己的完整人格文件。\n不预设新的身份。','existing_persona_choice':'use_original_as_is'})
        assert checked['exit_code']==0, checked
        assert native_job('initialize', {'step':'route','route':'local'})['exit_code']==0
        assert native_job('initialize', {'step':'ship'})['exit_code']==0
        native_job('backfill')
        prepared = post('/lune/native/gpt/prepare-continuation', {})
        assert prepared['ok'] and prepared['cursor_epoch']>0
        send('gpt','PERSONA_RELOAD_TRIGGER 请继续聊今天的事')
        send('gpt','NATIVE_WRITE_TRIGGER 我想周六去海边看风筝。')
        native_written = post('/lune/native/gpt/mcp', {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'latent_search','arguments':{'query':'周六去海边看风筝'}}})
        assert not native_written['result'].get('isError'), native_written
        print('Full Latent HTTP PASS: 10 original tools + tool-free archive/self-review/facts + durable cursor + native import + backup + original inspect/route/ship + backfill + archive-before-continuation checkpoint')
    print("HTTP flow passed: private chat → group → attachment → MCP → assistant-created durable todo → MiniMax + ElevenLabs speech")
