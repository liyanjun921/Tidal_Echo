"""Submit an external, untrusted wake event to Émoi's authenticated Room inbox.

Supports the Galatea Garden v1 injector stdin envelope and already normalized
CyberBoss/system event JSON. Does not run a model, fetch private content or reply
to WeChat; the Room scheduler handles the event when it next runs.
"""
import json
import os
import sys
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

SCOPES = {"gpt", "claude", "group_gpt", "group_claude"}
SOURCES = {"garden", "gmail", "cove", "calendar", "device", "manual", "system"}
MAX_BYTES = 65536


def _text(value, field, limit):
    if not isinstance(value, str):
        raise ValueError(field + " must be text")
    result = " ".join(value.split())
    if not result or len(result) > limit or "\x00" in result:
        raise ValueError(field + " is invalid")
    return result


def normalize(event):
    if not isinstance(event, dict):
        raise ValueError("expected JSON object")
    if event.get("version") == 1 and event.get("type") == "garden_wake":
        reason = _text(event.get("reason"), "reason", 120)
        message = _text(event.get("message"), "message", 4096)
        # The Garden wake v1 envelope has no stable event id. A fresh id can
        # duplicate on a retry; see the deployment guide before enabling.
        return {
            "source": "garden",
            "event_id": "garden-" + uuid.uuid4().hex,
            "type": "garden.wake",
            "summary": ("Garden event [" + reason + "]: " + message)[:600],
            "priority": 70,
            "ttl_seconds": 86400,
        }

    source = event.get("source")
    if source not in SOURCES:
        raise ValueError("unsupported source; use system for CyberBoss")
    result = {
        "source": source,
        "event_id": _text(event.get("event_id"), "event_id", 180),
        "type": _text(event.get("type"), "type", 80),
        "summary": _text(event.get("summary"), "summary", 600),
        "priority": event.get("priority", 50),
        "ttl_seconds": event.get("ttl_seconds", 86400),
    }
    if not isinstance(result["priority"], int) or isinstance(result["priority"], bool) or not 1 <= result["priority"] <= 100:
        raise ValueError("invalid priority")
    if not isinstance(result["ttl_seconds"], int) or isinstance(result["ttl_seconds"], bool) or not 60 <= result["ttl_seconds"] <= 604800:
        raise ValueError("invalid ttl_seconds")
    if "resource_ref" in event:
        result["resource_ref"] = _text(event["resource_ref"], "resource_ref", 300)
    return result


def endpoint():
    base = os.environ.get("EMOI_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
    parsed = urlparse(base)
    is_loopback = parsed.hostname in ("127.0.0.1", "localhost", "::1")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("EMOI_BASE_URL must be an origin without credentials or path")
    if not ((parsed.scheme == "https" and parsed.hostname) or (parsed.scheme == "http" and is_loopback)):
        raise ValueError("use HTTPS or local loopback HTTP")
    scope = os.environ.get("EMOI_SCOPE", "")
    if scope not in SCOPES:
        raise ValueError("EMOI_SCOPE must be one of: " + ", ".join(sorted(SCOPES)))
    secret = os.environ.get("EMOI_RELAY_SECRET") or os.environ.get("RELAY_SECRET")
    if not secret:
        raise ValueError("set EMOI_RELAY_SECRET or RELAY_SECRET privately")
    return base + "/relay/emoi/wren/" + scope + "/events", secret


class NoRedirect(HTTPRedirectHandler):
    """Never forward the relay Bearer token to a redirected endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    try:
        raw = sys.stdin.buffer.readline(MAX_BYTES + 1)
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError("input JSON line is missing or too large")
        event = normalize(json.loads(raw.decode("utf-8")))
        url, secret = endpoint()
        payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
        req = Request(url, payload, {"Authorization": "Bearer " + secret,
                                     "Content-Type": "application/json"}, method="POST")
        with build_opener(NoRedirect).open(req, timeout=10) as response:
            result = json.load(response)
        if not result.get("ok"):
            raise ValueError("Émoi did not acknowledge the event")
        # Do not log event content, tokens or user details.
        print(json.dumps({"ok": True, "id": result.get("id"),
                          "duplicate": bool(result.get("duplicate"))}))
        return 0
    except HTTPError as exc:
        print("Émoi rejected event (HTTP " + str(exc.code) + ")", file=sys.stderr)
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        print("Émoi event error: " + str(exc), file=sys.stderr)
    except (URLError, TimeoutError, OSError):
        print("Émoi event endpoint unavailable", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
