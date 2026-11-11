"""A live web process alone must not count as a ready chat backend."""
from unittest.mock import AsyncMock, patch
import unittest
from fastapi.testclient import TestClient
from tests import test_emoi as fixtures
from backend.emoi_server import app


class ReadinessTests(unittest.TestCase):
    def test_api_loop_failure_is_unready_without_leaking_details(self):
        with TestClient(app) as client, patch("backend.emoi_server.httpx.AsyncClient.get", new=AsyncMock(side_effect=OSError("private marker"))):
            r = client.get("/readyz")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"ok": False})

    def test_both_services_ready_but_missing_required_latent_is_not(self):
        import httpx
        response = httpx.Response(200, json={"ok": True, "private": "never expose"})
        with TestClient(app) as client, patch("backend.emoi_server.httpx.AsyncClient.get", new=AsyncMock(return_value=response)):
            with patch.dict("os.environ", {"EMOI_LATENT_AUTO_SETUP": "0"}):
                self.assertEqual(client.get("/readyz").json(), {"ok": True})
            with patch.dict("os.environ", {"EMOI_LATENT_AUTO_SETUP": "1"}), patch("backend.emoi_memory.LatentEngine.passive_status", return_value={"assets_ready": False}):
                self.assertEqual(client.get("/readyz").status_code, 503)
