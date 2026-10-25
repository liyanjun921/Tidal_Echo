"""Official plan auth and Responses contracts. No real accounts or inference."""
import asyncio
import concurrent.futures
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import zipfile

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from tests import test_lune as fixtures
import lune_auth as auth
import lune_plan as plan


class SubscriptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.signing_key.public_key()))
        cls.jwk.update(kid="test-key", alg="RS256")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = auth.PlanStore(Path(self.tmp.name) / "private" / "chatgpt-plan.json")
        self.environment = patch.dict(os.environ, {"CHATGPT_PLAN_FILE": str(self.store.path)})
        self.environment.start()
        auth._keys.update(keys=[self.jwk], until=time.time() + 300)
        self.old_config = fixtures.loop.load_config()

    def tearDown(self):
        fixtures.loop.save_config(self.old_config)
        self.environment.stop()
        self.tmp.cleanup()

    def identity_token(self, client="issued-client", subject="user-one", nonce="nonce", **extra):
        return jwt.encode({"iss": auth.ISSUER, "aud": client, "sub": subject, "iat": int(time.time()), "exp": int(time.time()) + 3600, "email": "fixture@example.invalid", "nonce": nonce, **extra}, self.signing_key, algorithm="RS256", headers={"kid": "test-key"})

    def tokens(self, nonce="nonce", **extra):
        return {"access_token": "private-access-marker", "refresh_token": "private-refresh-marker", "id_token": self.identity_token(nonce=nonce), "scope": auth.SCOPES, "expires_in": 3600, "token_type": "Bearer", **extra}

    def connect(self, scope=None):
        pending = self.store.begin("http://127.0.0.1:1455/auth/callback")
        tokens = self.tokens(pending["nonce"])
        if scope is not None:
            tokens["scope"] = scope
        with patch("lune_auth.token_request", return_value=tokens):
            return self.store.finish(pending, {"state": pending["state"], "code": "fixture-code", "client_id": "issued-client"})

    def test_state_pkce_nonce_and_one_time_callback(self):
        pending = self.store.begin("http://127.0.0.1:1455/auth/callback")
        query = parse_qs(urlsplit(pending["url"]).query)
        self.assertEqual(query["client_id"], ["dynamic_agent_client"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertNotEqual(query["code_challenge"][0], pending["verifier"])
        with patch("lune_auth.token_request") as exchange:
            with self.assertRaises(auth.PlanError):
                self.store.finish(pending, {"state": "wrong", "code": "c"})
            exchange.assert_not_called()
        with patch("lune_auth.token_request", return_value=self.tokens(pending["nonce"])) as exchange:
            result = self.store.finish(pending, {"state": pending["state"], "code": "code", "client_id": "issued-client"})
            self.assertEqual(exchange.call_args.args[0]["client_id"], "issued-client")
        self.assertTrue(result["ready"])
        with self.assertRaises(auth.PlanError):
            self.store.finish(pending, {"state": pending["state"], "code": "code", "client_id": "issued-client"})
        bad = self.store.begin("http://127.0.0.1:1455/auth/callback")
        with patch("lune_auth.token_request", return_value=self.tokens("different-nonce")):
            with self.assertRaises(auth.PlanError):
                self.store.finish(bad, {"state": bad["state"], "code": "code", "client_id": "issued-client"})

    def test_signature_identity_and_returning_client_are_verified(self):
        status = self.connect()
        pending = self.store.begin("http://127.0.0.1:12345/auth/callback", status["active"])
        self.assertNotIn("agent_name_hint", parse_qs(urlsplit(pending["url"]).query))
        with patch("lune_auth.token_request") as exchange:
            with self.assertRaises(auth.PlanError):
                self.store.finish(pending, {"state": pending["state"], "code": "code", "client_id": "other-client"})
            exchange.assert_not_called()
        forged = jwt.encode({"iss": auth.ISSUER, "aud": "issued-client", "sub": "user-one", "exp": time.time() + 300, "iat": time.time()}, rsa.generate_private_key(public_exponent=65537, key_size=2048), algorithm="RS256", headers={"kid": "test-key"})
        with self.assertRaises(auth.PlanError):
            auth.verify_identity(forged, "issued-client")

    def test_identity_only_login_is_not_plan_permission(self):
        status = self.connect("openid profile email")
        self.assertFalse(status["ready"])
        with self.assertRaises(auth.PlanError) as error:
            self.store.access()
        self.assertEqual(error.exception.code, "sharing_disabled")
        self.assertNotIn("private-access-marker", json.dumps(status))
        self.assertNotIn("id_token", json.dumps(status))

    def test_refresh_is_serialized_and_rotating_credentials_are_atomic(self):
        self.connect()
        with self.store.locked():
            data = self.store.read()
            data["accounts"][data["active"]]["expires_at"] = 0
            self.store.write(data)
        def refresh(body):
            self.assertEqual(body["refresh_token"], "private-refresh-marker")
            self.assertNotIn("scope", body)
            time.sleep(.03)
            return {"access_token": "next-access", "refresh_token": "next-refresh", "expires_in": 3600}
        with patch("lune_auth.token_request", side_effect=refresh) as exchange:
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda _: self.store.access(), range(2)))
            self.assertEqual(exchange.call_count, 1)
        self.assertTrue(all(r["access_token"] == "next-access" for r in results))
        self.assertEqual(self.store.read()["accounts"][self.store.read()["active"]]["refresh_token"], "next-refresh")
        if os.name != "nt":
            self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)

    def test_import_preserves_destination_host_and_rejects_expired_or_forged_files(self):
        self.connect()
        source = self.store.read()
        record = {"format": "lune-chatgpt-session-v1", "session": source["accounts"][source["active"]]}
        target = auth.PlanStore(Path(self.tmp.name) / "target" / "chatgpt-plan.json")
        target.begin("http://127.0.0.1:1456/auth/callback")
        host = target.read()["host_id"]
        target.import_session(record)
        self.assertEqual(target.read()["host_id"], host)
        self.assertNotEqual(host, source["host_id"])
        with self.assertRaises(auth.PlanError):
            target.import_session({**record, "session": {**record["session"], "subject": "forged"}})
        with self.assertRaises(auth.PlanError):
            target.import_session({**record, "session": {**record["session"], "expires_at": 0}})

    def test_sign_out_reports_unconfirmed_revocation_and_keeps_registration(self):
        status = self.connect()
        with patch("lune_auth.httpx.Client.get", side_effect=httpx.ConnectError("unavailable")):
            result = self.store.sign_out(status["active"])
        self.assertFalse(result["revoked"])
        self.assertFalse(self.store.status()["ready"])
        self.assertEqual(self.store.read()["accounts"][status["active"]]["client_id"], "issued-client")
        with self.assertRaises(auth.PlanError):
            self.store.access()

    def test_responses_request_keeps_context_images_and_tool_results(self):
        messages = [{"role": "system", "content": "private persona"}, {"role": "user", "content": [{"type": "text", "text": "ask"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}}]}, {"role": "assistant", "content": None, "responses_items": [{"type": "reasoning", "encrypted_content": "opaque"}, {"type": "function_call", "call_id": "call-1", "name": "lookup", "namespace": "lune", "arguments": "{}"}]}, {"role": "tool", "tool_call_id": "call-1", "content": "result"}]
        body = plan.response_body("available-model", messages, [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object", "properties": {}}}}])
        self.assertFalse(body["store"])
        self.assertTrue(body["stream"])
        self.assertEqual(body["instructions"], "private persona")
        self.assertEqual(body["tools"][0]["type"], "namespace")
        self.assertEqual(body["input"][0]["content"][1]["type"], "input_image")
        self.assertEqual(body["input"][-1]["call_id"], "call-1")
        for field in ("temperature", "max_output_tokens", "previous_response_id", "conversation"):
            self.assertNotIn(field, body)

    def test_stream_requires_completed_and_usage_failure_is_not_success(self):
        self.connect()
        real_client = httpx.AsyncClient
        captured = []
        def run(stream_events):
            def handle(request):
                self.assertEqual(str(request.url), auth.RESOURCE + "/responses")
                self.assertEqual(request.headers["Authorization"], "Bearer private-access-marker")
                captured.append(json.loads(request.content))
                return httpx.Response(200, text="".join("data: " + json.dumps(e) + "\n\n" for e in stream_events), headers={"content-type": "text/event-stream"})
            with patch("lune_plan.httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw)):
                return asyncio.run(plan.chat({"model": "available-model"}, [{"role": "user", "content": "hello"}], None, store=self.store))
        output = run([{"type": "response.output_text.delta", "delta": "Hello"}, {"type": "response.completed", "response": {"status": "completed", "output": [], "usage": {"input_tokens": 2}}}])
        self.assertEqual(output["text"], "Hello")
        self.assertEqual(output["billing_mode"], "chatgpt_plan")
        with self.assertRaises(auth.PlanError):
            run([{"type": "response.output_text.delta", "delta": "partial"}])
        with self.assertRaises(auth.PlanError) as error:
            run([{"type": "response.failed", "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded", "message": "private provider details"}}}])
        self.assertEqual(error.exception.status, 429)
        self.assertNotIn("private provider details", error.exception.message)

    def test_subscription_selection_never_uses_stored_api_key(self):
        loop = fixtures.loop
        with TestClient(loop.app) as client:
            for agent, mode in (("gpt", "chatgpt_plan"), ("claude", "claude_subscription")):
                setup = client.post("/loop/agents", json={"agent": agent, "connection_mode": "api", "url": "https://example.invalid/v1", "key": "previous-api-key-marker", "model": "api-model"})
                self.assertEqual(setup.status_code, 200)
                r = client.post("/loop/agents", json={"agent": agent, "connection_mode": mode, "subscription_model": "available-model"})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(r.json()["agents"][agent]["key_set"])
                token = loop.CURRENT_AGENT.set(agent)
                try:
                    with patch.object(loop, "stream_chat") as api, patch.object(loop, "complete_chat") as api2:
                        with self.assertRaises(loop.ModelError):
                            asyncio.run(loop.run_model([{"role": "user", "content": "hello"}], None))
                        api.assert_not_called()
                        api2.assert_not_called()
                finally:
                    loop.CURRENT_AGENT.reset(token)
            self.assertEqual(client.post("/loop/agents", json={"agent": "claude", "connection_mode": "chatgpt_plan"}).status_code, 422)
            self.assertFalse(client.get("/loop/subscriptions").json()["claude"]["ready"])

    def test_loopback_callback_completes_without_exposing_credentials(self):
        result = auth.start_login(self.store)
        query = parse_qs(urlsplit(result["authorization_url"]).query)
        callback = query["redirect_uri"][0]
        with patch("lune_auth.token_request", return_value=self.tokens(query["nonce"][0])):
            with httpx.Client(trust_env=False) as client:
                response = client.get(callback, params={"state": query["state"][0], "code": "test-code", "client_id": "issued-client"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("private-access-marker", response.text)
        self.assertTrue(self.store.status()["ready"])
        with self.assertRaises(auth.PlanError):
            self.store.begin("https://example.com/auth/callback")

    def test_model_catalog_is_account_specific_and_preserves_order(self):
        self.connect()
        real_client = httpx.AsyncClient
        def handle(request):
            self.assertEqual(request.headers["Authorization"], "Bearer private-access-marker")
            self.assertEqual(str(request.url), auth.RESOURCE + "/models")
            return httpx.Response(200, json={"models": [{"slug": "second", "display_name": "Second", "visibility": "list"}, {"slug": "hidden", "visibility": "hidden"}, {"slug": "first", "visibility": "list"}]})
        with patch("lune_plan.httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw)):
            result = asyncio.run(plan.models(self.store))
        self.assertEqual([r["id"] for r in result["models"]], ["second", "first"])

    def test_cancel_gate_stops_before_inference_and_tool_calls_require_authorization(self):
        self.connect()
        def cancelled():
            raise asyncio.CancelledError()
        with patch("lune_plan.httpx.AsyncClient") as client:
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(plan.chat({"model": "m"}, [], None, store=self.store, gate=cancelled))
            client.assert_not_called()
        real_client = httpx.AsyncClient
        def handle(request):
            event = {"type": "response.completed", "response": {"status": "completed", "output": [{"type": "function_call", "call_id": "c", "name": "unauthorized", "namespace": "lune", "arguments": "{}"}]}}
            return httpx.Response(200, text="data: " + json.dumps(event) + "\n\n")
        with patch("lune_plan.httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw)):
            with self.assertRaises(auth.PlanError):
                asyncio.run(plan.chat({"model": "m"}, [], None, store=self.store))

    def test_owner_helper_zip_excludes_credentials_and_uploads(self):
        with TestClient(fixtures.relay.app) as client:
            self.assertEqual(client.get("/lune/chatgpt-helper").status_code, 401)
            r = client.get("/lune/chatgpt-helper", headers={"Authorization": "Bearer test-owner-secret-only"})
        self.assertEqual(r.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
            self.assertEqual(set(archive.namelist()), {"chatgpt_login.py", "lune_auth.py", "requirements.txt", "README.txt", "start-windows.cmd"})
        self.assertFalse(fixtures.loop.attach_allowed(self.store.path))
        self.assertFalse(fixtures.loop.attach_allowed(Path(fixtures.relay.UPLOAD_DIR) / "lune-chatgpt-connection.json"))


if __name__ == "__main__":
    unittest.main()
