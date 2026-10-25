"""Speech routing/configuration tests. All audio and keys are synthetic."""
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from tests import test_lune as fixtures
relay = fixtures.relay


class SpeechTests(unittest.TestCase):
    setUp = fixtures.OwnerDataTests.setUp
    tearDown = fixtures.OwnerDataTests.tearDown

    def configure(self, provider="elevenlabs", **values):
        config = self.client.get("/lune/speech").json()
        r = self.client.patch("/lune/speech", json={"provider": provider, "version": config["version"], "providers": {provider: {"key": "synthetic-speech-key", "voice_id": "fixture_voice", **values}}})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_auth_masks_keys_retains_blank_and_conflicts(self):
        for route in ("/lune/speech", "/app/tts"):
            r = self.client.get(route, headers={"Authorization": "Bearer wrong"}) if route == "/lune/speech" else self.client.post(route, json={"text": "x"}, headers={"Authorization": "Bearer wrong"})
            self.assertEqual(r.status_code, 401)
        config = self.configure()
        self.assertTrue(config["providers"]["elevenlabs"]["key_set"])
        self.assertNotIn("synthetic-speech-key", json.dumps(config))
        r = self.client.patch("/lune/speech", json={"provider": "elevenlabs", "version": config["version"], "providers": {"elevenlabs": {"key": "", "voice_id": "changed"}}})
        self.assertTrue(r.json()["providers"]["elevenlabs"]["key_set"])
        self.assertEqual(self.client.patch("/lune/speech", json={"provider": "minimax", "version": config["version"]}).status_code, 409)
        relay.speech_runtime["init"]()
        self.assertEqual(self.client.get("/lune/speech").json()["providers"]["elevenlabs"]["voice_id"], "changed")

    def test_elevenlabs_request_and_binary_response(self):
        self.configure(base_url="https://api.elevenlabs.io/v1")
        audio = b"ID3fixture-mp3"
        response = io.BytesIO(audio)
        response.headers = {"Content-Type": "audio/mpeg"}
        with patch("backend.speech.urllib.request.urlopen", return_value=response) as send:
            r = self.client.post("/app/tts", json={"text": "你好"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.content, audio)
        self.assertEqual(r.headers["cache-control"], "no-store")
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.elevenlabs.io/v1/text-to-speech/fixture_voice?output_format=mp3_44100_128")
        self.assertEqual(request.get_header("Xi-api-key"), "synthetic-speech-key")
        self.assertEqual(json.loads(request.data), {"text": "你好", "model_id": "eleven_multilingual_v2"})

    def test_minimax_selection_uses_its_own_voice_and_key(self):
        self.configure("minimax", voice_id="Chinese (Mandarin)_Warm_Bestie", model="speech-02-hd", group_id="group")
        response = io.BytesIO(json.dumps({"data": {"audio": b"ID3minimax".hex()}}).encode())
        with patch("backend.app.urllib.request.urlopen", return_value=response) as send:
            r = self.client.post("/app/tts", json={"text": "hello"})
        self.assertEqual(r.content, b"ID3minimax")
        request = send.call_args.args[0]
        self.assertIn("/v1/t2a_v2?GroupId=group", request.full_url)
        self.assertEqual(json.loads(request.data)["voice_setting"]["voice_id"], "Chinese (Mandarin)_Warm_Bestie")
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-speech-key")

    def test_provider_failure_never_falls_back_or_echoes_secrets(self):
        self.configure()
        error = urllib.error.HTTPError("https://api.elevenlabs.io", 429, "SECRET_ERROR_TEXT", {}, None)
        with patch("backend.speech.urllib.request.urlopen", side_effect=error) as send:
            r = self.client.post("/app/tts", json={"text": "test"})
        self.assertEqual(r.status_code, 502)
        self.assertIn("429", r.text)
        self.assertNotIn("SECRET_ERROR_TEXT", r.text)
        self.assertEqual(send.call_count, 1)

    def test_bad_config_and_text_are_rejected_before_provider_request(self):
        self.configure()
        for text in ("", "x" * 901, 17):
            with patch("backend.speech.urllib.request.urlopen") as send:
                self.assertEqual(self.client.post("/app/tts", json={"text": text}).status_code, 422)
                send.assert_not_called()
        for base in ("http://example.com", "https://user:password@example.com", "https://example.com?key=secret"):
            version = self.client.get("/lune/speech").json()["version"]
            r = self.client.patch("/lune/speech", json={"provider": "elevenlabs", "version": version, "providers": {"elevenlabs": {"base_url": base}}})
            self.assertEqual(r.status_code, 422)
        self.assertEqual(self.client.post("/app/tts", json=[]).status_code, 422)


if __name__ == "__main__":
    unittest.main()
