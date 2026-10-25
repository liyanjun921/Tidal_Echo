"""Starts isolated services and synthetic providers, then runs real browser flow."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import httpx

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
children = []
with tempfile.TemporaryDirectory(prefix="lune-e2e-") as tmp:
    env = {**os.environ, "RELAY_SECRET": "fixture-owner-secret", "RELAY_DB": tmp + "/relay.db", "RELAY_UPLOAD_DIR": tmp + "/uploads", "LOOP_CONFIG": tmp + "/config.json", "LOOP_CACHE_DIR": tmp + "/cache", "RELAY_BRAIN_FILE": tmp + "/brain", "RELAY_URL": "http://127.0.0.1:8089/relay", "PORT": "8089", "LUNE_TEST_REQUESTS": tmp + "/requests.jsonl"}
    # All E2E destinations are loopback fixtures; do not initialize ambient proxies.
    env = {k: v for k, v in env.items() if not k.upper().endswith("_PROXY")}
    output = Path(env.get("LUNE_TEST_OUTPUT", tmp + "/screenshots"))
    output.mkdir(parents=True, exist_ok=True)
    env["LUNE_TEST_OUTPUT"] = str(output)
    log = open(tmp + "/services.log", "w+")
    try:
        children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "provider_fixture:app", "--app-dir", "tests", "--port", "8766", "--no-access-log"], cwd=root, env=env, stdout=log, stderr=log))
        children.append(subprocess.Popen([sys.executable, "tests/mcp_fixture.py"], cwd=root, env=env, stdout=log, stderr=log))
        children.append(subprocess.Popen([sys.executable, "scripts/run_lune.py"], cwd=root, env=env, stdout=log, stderr=log, start_new_session=True))
        with httpx.Client(trust_env=False) as client:
            for _ in range(300):
                try:
                    if client.get("http://127.0.0.1:8089/relay/lune/rooms", headers={"Authorization": "Bearer fixture-owner-secret"}).status_code == 200 and client.get("http://127.0.0.1:8089/readyz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError("test services did not start")
        if "--http-only" in sys.argv:
            subprocess.run([sys.executable, "tests/http_flow.py"], cwd=root, env=env, check=True, timeout=180)
        else:
            subprocess.run([env.get("CODEX_PRIMARY_RUNTIME_NODE", "node"), "tests/browser.cjs"], cwd=root, env=env, check=True, timeout=90)
        if env.get('LUNE_OMBRE_SOURCE'):
            subprocess.run([sys.executable, 'tests/ombre_flow.py'], cwd=root, env=env, check=True, timeout=240)
        if env.get('LUNE_FOLIO_SOURCE'):
            subprocess.run([sys.executable,'tests/folio_flow.py'],cwd=root,env=env,check=True,timeout=240)
        subprocess.run([sys.executable, 'tests/continuity_flow.py'], cwd=root, env=env, check=True, timeout=240)
        with httpx.Client(trust_env=False, timeout=30, headers={"Authorization": "Bearer fixture-owner-secret"}) as client:
            base = "http://127.0.0.1:8089/relay"
            saved = client.get(base + "/lune/rooms/gpt/messages").json()["messages"]
            memories = client.get(base + "/lune/memories").json()["memories"]
            diaries = client.get(base + "/lune/duet?room=gpt").json()
            if env.get('LUNE_FOLIO_SOURCE'):
                client.post(base+'/lune/ombre/gpt/open',json={}).raise_for_status()
            folio = client.get('http://127.0.0.1:8089/ombre/gpt/api/folio/scoring-config').json() if env.get('LUNE_FOLIO_SOURCE') else None
            children[2].terminate()
            children[2].wait(timeout=20)
            children[2] = subprocess.Popen([sys.executable, "scripts/run_lune.py"], cwd=root, env=env, stdout=log, stderr=log, start_new_session=True)
            for _ in range(300):
                try:
                    if client.get("http://127.0.0.1:8089/readyz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                raise AssertionError("services did not become ready after restart")
            assert client.get(base + "/lune/rooms/gpt/messages").json()["messages"] == saved
            assert client.get(base + "/lune/memories").json()["memories"] == memories
            assert client.get(base + "/lune/duet?room=gpt").json() == diaries
            if folio:
                client.post(base+'/lune/ombre/gpt/open',json={}).raise_for_status()
                assert client.get('http://127.0.0.1:8089/ombre/gpt/api/folio/scoring-config').json()==folio
                assert any(x.get('summary')=='FOLIO_REFINED_SUMMARY' for x in client.get('http://127.0.0.1:8089/ombre/gpt/api/folio/buckets').json())
            if env.get('LUNE_OMBRE_SOURCE'):
                from backend import ombre_runtime as ob
                with patch.dict(os.environ, env):
                    result = __import__('asyncio').run(ob.call('gpt', 'breath_search', {'query': 'OMBRE_PRIVATE_MARKER', 'max_results': 2}))
                assert '用户说我们周日去海边看蓝色风筝。' in ob.text_result(result), result
                print('Ombre restart PASS: original vault and search survive full supervisor restart')
            if env.get("LUNE_LATENT_SOURCE"):
                result = client.post(base + "/lune/native/gpt/mcp", json={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"latent_search","arguments":{"query":"周六去海边看风筝"}}}).json()
                assert not result["result"].get("isError"), result
            print("Restart persistence PASS: both services ready; messages, saved memories and native archive survive restart")
        requests = [json.loads(line) for line in Path(env["LUNE_TEST_REQUESTS"]).read_text().splitlines()]
        group = [r for r in requests if "GROUP_UI_MARKER" in json.dumps(r, ensure_ascii=False)]
        assert len(group) >= 2
        for r in group:
            assert "PRIVATE_UI_MARKER" not in json.dumps(r), "private chat or memory leaked to group"
        claude = next(r for r in group if r["model"] == "fixture-claude")
        projection = json.dumps(claude)
        assert projection.index("GROUP_UI_MARKER") < projection.index("TEST_GPT"), "group turn order"
        assert any("ATTACHMENT_BODY_MARKER" in json.dumps(r) for r in requests)
        assert any(m.get("role") == "tool" and "TOOL_RESULT_MARKER" in m.get("content", "") for r in requests for m in r["messages"])
        if env.get("LUNE_PASSIVE_MODEL_CACHE"):
            native_tools = {t["function"]["name"] for r in requests for t in r.get("tools", []) if t.get("type") == "function"}
            assert {"latent_search", "latent_append", "latent_thread_close", "latent_fact_backfill", "latent_note_reply"} <= native_tools
            assert "latent_passive_recall" not in native_tools
            native = [r for r in requests if "〔历史证据〕" in json.dumps(r, ensure_ascii=False)]
            assert native, "native recall never reached an actual provider HTTP request"
            assert any("我喜欢蓝色鸢尾" in json.dumps(r, ensure_ascii=False) for r in native)
        print("E2E PASS: real HTTP + SQLite + both provider adapters + MCP; synthetic credentials only; " + ("UI checked separately" if "--http-only" in sys.argv else "browser UI included"))
    except Exception:
        log.flush()
        print(Path(tmp + "/services.log").read_text()[-9000:])
        subprocess.run([sys.executable, "-c", "import sys,asyncio;sys.path.insert(0,'examples');import api_loop as l;l.CURRENT_AGENT.set('gpt');\ntry: print(asyncio.run(l.run_model([{'role':'user','content':'diagnostic'}],None,stream=False)))\nexcept Exception as e: print(type(e).__name__,getattr(e,'detail',str(e)))"], cwd=root, env=env)
        raise
    finally:
        for child in reversed(children):
            child.terminate()
        for child in children:
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
        log.close()
