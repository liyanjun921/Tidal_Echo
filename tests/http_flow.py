"""Real HTTP flow against isolated run_e2e.py services; synthetic credentials only."""
import time
import uuid
import httpx

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
    print("HTTP flow passed: private chat → group → attachment → MCP → assistant-created durable todo")
