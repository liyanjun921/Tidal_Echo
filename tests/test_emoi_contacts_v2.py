"""The v2 contact API is a PRIVATE and isolated registry. No fake model delivery."""
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
from backend.emoi_contacts import connect, register
from backend.emoi_autonomy import DEFAULTS, followup_delay, is_quiet, owner_call_request
from examples.contact_actions import decode, sticker_options
from datetime import datetime, timezone


class ContactIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = self.path = str(Path(self.tmp.name) / "emoi-v2-test.db")
        self.uploads = Path(self.tmp.name) / "uploads"
        self.uploads.mkdir()
        app = FastAPI()
        def check_auth(request):
            if request.headers.get("authorization") != "Bearer test-only-owner":
                raise HTTPException(401, "unauthorized")
        runtime = self.runtime = register(app, {"DB_PATH":path,"UPLOAD_DIR":self.uploads,"check_auth":check_auth,"loop_base_url":lambda:"http://loop.test"})
        runtime["init"]()
        self.client=TestClient(app)
        self.h={"Authorization":"Bearer test-only-owner"}
    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def post(self,url,payload):
        return self.client.post(url,headers=self.h,json=payload)
    def create(self,name):
        result=self.post("/emoi/v2/contacts",{"id":str(uuid4()),"name":name})
        self.assertEqual(result.status_code,200,result.text)
        return result.json()

    def test_model_action_formats_and_exact_shared_sticker_names(self):
        first, second = "a" * 64, "b" * 64
        options = sticker_options([{"id": first, "name": "抱抱.png"}, {"id": second, "name": "抱抱.webp"}])
        reply = decode("来接我呀。［表情包：抱抱 (2)］\n【我向你发起了视频通话】", options, calls=True)
        self.assertEqual(reply, {"call": "video", "sticker": second, "text": "来接我呀。"})
        self.assertEqual(decode("好呀 [call:voice]", options, calls=True)["call"], "voice")
        self.assertEqual(decode("【语音通话】", options), {"text": ""})
        self.assertEqual(decode("抱抱 [表情包:猜测]", options), {"text": "抱抱"})
        self.assertEqual(decode(f"[sticker:{first}]", options)["sticker"], first)

    def test_owner_call_words_create_invites_without_asking_model(self):
        created = self.create("GPT")
        ident = created["contact"]["id"]
        self.client.patch(f"/emoi/v2/contacts/{ident}", headers=self.h, json={"model_route": "gpt"})
        messages = "/emoi/v2/conversations/" + created["conversation_id"] + "/messages"
        inbox = "/emoi/v2/call-inbox"
        with patch("httpx.AsyncClient.post", side_effect=AssertionError("explicit calls must work without model output")):
            first_body = {"text": "老公给我打个电话试试", "nonce": uuid4().hex}
            first = self.post(messages, first_body)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertTrue(first.json()["call_queued"])
            self.assertFalse(first.json()["model_dispatched"])
            voice = self.client.get(inbox, headers=self.h).json()["invite"]
            self.assertEqual((voice["mode"], voice["trigger"]), ("voice", "owner_request"))
            self.assertTrue(self.post(messages, first_body).json()["already_saved"])
            second = self.post(messages, {"text": "前端这个视频通话", "nonce": uuid4().hex})
            self.assertTrue(second.json()["call_queued"])
        video = self.client.get(inbox, headers=self.h).json()["invite"]
        self.assertEqual((video["mode"], video["trigger"]), ("video", "owner_request"))
        self.assertNotEqual(voice["id"], video["id"])
        expired = self.client.patch(inbox + "/" + voice["id"], headers=self.h, json={"action": "accept"})
        self.assertEqual(expired.status_code, 409)
        answered = self.client.patch(inbox + "/" + video["id"], headers=self.h, json={"action": "accept"})
        self.assertEqual(answered.status_code, 200, answered.text)
        rows = self.client.get(messages, headers=self.h).json()["messages"]
        self.assertEqual([row["author"] for row in rows], ["human", "contact", "human", "contact"])
        self.assertEqual(rows[1]["call_state"], "superseded")

    def test_call_command_does_not_match_negation_or_discussion(self):
        self.assertEqual(owner_call_request("老公…打电话…"), "voice")
        self.assertEqual(owner_call_request("给我打个视频通话"), "video")
        for message in ("不要给我打电话", "你说过要打电话", "我刚打了个电话", "什么是视频通话？", "‘给我打电话’"):
            self.assertIsNone(owner_call_request(message))

    def test_owner_can_like_unlike_and_comment_once_per_nonce(self):
        post_id = str(uuid4())
        path = "/emoi/v2/moments"
        self.assertEqual(self.post(path, {"id":post_id,"text":"今天天气好"}).status_code, 200)
        like, comment = f"{path}/{post_id}/like", f"{path}/{post_id}/comments"
        self.assertEqual(self.client.put(like, json={"liked":True}).status_code, 401)
        self.assertEqual(self.client.put(like, headers=self.h, json={"liked":"yes"}).status_code, 422)
        for _ in range(2):
            self.assertTrue(self.client.put(like, headers=self.h, json={"liked":True}).json()["liked_by_me"])
        body = {"id": str(uuid4()), "text": "我也喜欢"}
        self.assertEqual(self.client.post(comment, json=body).status_code, 401)
        for _ in range(2):
            response = self.post(comment, body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(response.json()["my_comments"]), 1)
        self.assertEqual(self.post(comment, {**body, "text":"不同评论"}).status_code, 409)
        self.assertFalse(self.client.put(like, headers=self.h, json={"liked":False}).json()["liked_by_me"])
        post = self.client.get(path, headers=self.h).json()["posts"][0]
        self.assertFalse(post["liked_by_me"])
        self.assertEqual(post["my_comments"][0]["text"], body["text"])

    def test_ai_stickers_and_model_initiated_calls(self):
        created = self.create("甲")
        ident = created["contact"]["id"]
        endpoint = f"/emoi/v2/contacts/{ident}"
        self.client.patch(endpoint, headers=self.h, json={"model_route": "gpt"})
        rules = endpoint + "/message-rules"
        self.assertEqual(self.client.put(rules, headers=self.h, json={"calls": True}).status_code, 200)
        stored = "att-" + uuid4().hex[:14] + ".gif"
        (self.uploads / stored).write_bytes(b"test gif")
        sticker = "a" * 64
        result = self.post("/emoi/v2/stickers/shared", {
            "id": sticker, "name": "抱抱", "pack": "日常", "upload": stored,
        })
        self.assertEqual(result.status_code, 200, result.text)
        library = self.client.get("/emoi/v2/stickers/shared", headers=self.h)
        self.assertEqual(library.headers["cache-control"], "no-store")
        self.assertEqual(library.json()["items"][0]["attachment"]["url"], "/uploads/" + stored)
        messages = "/emoi/v2/conversations/" + created["conversation_id"] + "/messages"

        async def fake_reply(client, url, *, json, **kwargs):
            self.assertTrue(json["can_call"])
            self.assertEqual(json["stickers"][0]["id"], sticker)
            is_call = json["history"][-1]["text"] == "视频"
            raw = "接电话 【表情包：抱抱】【视频通话】" if is_call else "[表情包:抱抱]"
            reply = decode(raw, sticker_options(json["stickers"]), calls=json["can_call"])
            return httpx.Response(200, json=reply, request=httpx.Request("POST", url))

        with patch("httpx.AsyncClient.post", new=fake_reply):
            for value in ("表情", "视频"):
                sent = self.post(messages, {"text": value, "nonce": uuid4().hex})
                self.assertEqual(sent.status_code, 200, sent.text)
        rows = self.client.get(messages, headers=self.h).json()["messages"]
        self.assertEqual(rows[1]["attachment"]["kind"], "sticker")
        inbox = self.client.get("/emoi/v2/call-inbox", headers=self.h)
        self.assertEqual(inbox.headers["cache-control"], "no-store")
        invite = inbox.json()["invite"]
        self.assertEqual(invite["mode"], "video")
        self.assertGreater(invite["remaining_seconds"], 0)
        self.assertEqual(invite["id"], rows[3]["id"])
        self.assertEqual(rows[4]["attachment"]["url"], rows[1]["attachment"]["url"])
        answer = self.client.patch("/emoi/v2/call-inbox/" + invite["id"], headers=self.h, json={"action":"accept"})
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertIsNone(self.client.get("/emoi/v2/call-inbox", headers=self.h).json()["invite"])

    def test_manual_moment_uses_bound_contact_and_skips_phantom_user_message(self):
        created = self.create("甲")
        ident = created["contact"]["id"]
        endpoint = f"/emoi/v2/contacts/{ident}"
        self.client.patch(endpoint, headers=self.h, json={"model_route": "gpt"})

        async def fake_reply(client, url, *, json, **kwargs):
            self.assertEqual(json["initiative"], "moment")
            self.assertEqual(json["history"], [])
            self.assertEqual(json["route"], "gpt")
            self.assertEqual(json["moment_photo"], "text")
            return httpx.Response(200, json={"text": "今晚看到了月亮。", "image_prompt": "月亮"}, request=httpx.Request("POST", url))

        with patch("httpx.AsyncClient.post", new=fake_reply):
            result = self.post(endpoint + "/message-rules/run", {"mode": "moment", "photo": "text"})
        self.assertEqual(result.status_code, 200, result.text)
        required = self.post(endpoint + "/message-rules/run", {"mode": "moment", "photo": "image"})
        self.assertEqual(required.status_code, 422)
        feed = self.client.get("/emoi/v2/moments", headers=self.h).json()["posts"]
        self.assertEqual(feed[0]["contact_id"], ident)
        self.assertEqual(feed[0]["text"], "今晚看到了月亮。")
        self.assertIsNone(feed[0]["attachment"])

    def test_followup_delay_and_midnight_quiet_window(self):
        config = {**DEFAULTS, "threshold": 20, "quiet_start": "23:00", "quiet_end": "07:00", "zone": "UTC"}
        self.assertIsNone(followup_delay(config, 19))
        self.assertEqual(followup_delay(config, 20), 600)
        self.assertEqual(followup_delay(config, 60), 307.5)
        self.assertEqual(followup_delay(config, 100), 15)
        self.assertTrue(is_quiet(config, datetime(2026, 11, 15, 1, tzinfo=timezone.utc).timestamp()))
        self.assertFalse(is_quiet(config, datetime(2026, 11, 15, 7, tzinfo=timezone.utc).timestamp()))

    def test_offline_scheduler_delivers_one_message_and_one_reaction(self):
        created = self.create("甲")
        ident = created["contact"]["id"]
        endpoint = f"/emoi/v2/contacts/{ident}"
        self.client.patch(endpoint, headers=self.h, json={"model_route": "gpt"})
        rules = endpoint + "/message-rules"
        config = {"idle": True, "calls": True, "idle_minutes": 1, "quiet": False,
                  "reactions": True, "like_chance": 100, "comment_chance": 100, "comment_delay": 0}
        self.assertEqual(self.client.put(rules, headers=self.h, json=config).status_code, 200)
        with connect(self.path) as db:
            db.execute("UPDATE emoi_message_rules SET saved=?", (time.time() - 120,))
        self.assertEqual(self.post("/emoi/v2/moments", {"id": str(uuid4()), "text": "今天去散步"}).status_code, 200)

        async def fake_reply(client, url, *, json, **kwargs):
            self.assertEqual(json["history"], [])
            if json["initiative"] == "idle":
                reply = {"text": "想给你打电话", "call": "voice"}
            else:
                self.assertEqual(json["initiative"], "reaction")
                self.assertEqual(json["moment_text"], "今天去散步")
                reply = {"text": "下次一起走走"}
            return httpx.Response(200, json=reply, request=httpx.Request("POST", url))

        class StopWatch(Exception):
            pass

        async def stop(_):
            raise StopWatch

        with patch("httpx.AsyncClient.post", new=fake_reply), patch("backend.emoi_contacts.asyncio.sleep", new=stop):
            with self.assertRaises(StopWatch):
                asyncio.run(self.runtime["watch"]())
        invite = self.client.get("/emoi/v2/call-inbox", headers=self.h).json()["invite"]
        self.assertEqual(invite["mode"], "voice")
        self.assertEqual(self.client.get(rules, headers=self.h).json()["count"], 1)
        feed = self.client.get("/emoi/v2/moments", headers=self.h).json()["posts"]
        self.assertEqual(feed[0]["reactions"], [{"name": "甲", "liked": 1, "comment": "下次一起走走"}])

    def test_requires_owner_secret_even_for_lists(self):
        self.assertEqual(self.client.get("/emoi/v2/contacts").status_code,401)
        self.assertEqual(self.client.get("/emoi/v2/conversations").status_code,401)
        self.assertEqual(self.client.post("/emoi/v2/contacts",json={"name":"X"}).status_code,401)

    def test_two_contacts_never_share_identity_or_direct_messages(self):
        p=self.create("甲"); q=self.create("乙")
        a,b=p["contact"],q["contact"]
        self.assertNotEqual(a["id"],b["id"])
        self.assertNotEqual(a["memory_namespace"],b["memory_namespace"])
        self.assertNotEqual(a["desire_namespace"],b["desire_namespace"])
        self.assertNotEqual(p["conversation_id"],q["conversation_id"])
        self.assertFalse(a["connected"])
        route="/emoi/v2/conversations/"+p["conversation_id"]+"/messages"
        sent=self.post(route,{"text":"只有甲能看见这句话","nonce":"n"+uuid4().hex})
        self.assertEqual(sent.status_code,200,sent.text)
        self.assertFalse(sent.json()["model_dispatched"])
        first=self.client.get(route,headers=self.h).json()
        self.assertEqual(len(first["messages"]),1)
        other=self.client.get("/emoi/v2/conversations/"+q["conversation_id"]+"/messages",headers=self.h).json()
        self.assertEqual(other["messages"],[])
        self.assertFalse(other["model_connected"])

    def test_group_never_created_implicitly_and_members_only_user_choice(self):
        a=self.create("甲")["contact"]
        b=self.create("乙")["contact"]
        initial=self.client.get("/emoi/v2/conversations",headers=self.h).json()["conversations"]
        self.assertEqual(sum(x["kind"]=="group" for x in initial),0)
        group=self.post("/emoi/v2/conversations",{"title":"自建群","members":[a["id"],b["id"]]})
        self.assertEqual(group.status_code,200,group.text)
        data=group.json()["conversation"]
        self.assertEqual(set(data["members"]),{a["id"],b["id"]})
        self.assertNotEqual(data["memory_namespace"],a["memory_namespace"])
        self.assertNotEqual(data["memory_namespace"],b["memory_namespace"])
        self.assertEqual(self.post("/emoi/v2/conversations",{"title":"假群聊","members":["gpt"]}).status_code,422)
        patched=self.client.patch("/emoi/v2/conversations/"+data["id"],headers=self.h,json={"title":"自建新群","members":[b["id"]]})
        self.assertEqual(patched.status_code,200,patched.text)
        self.assertEqual(patched.json()["conversation"]["members"],[b["id"]])

    def test_namespace_cannot_be_changed_and_no_alias_crossover(self):
        a=self.create("第一位")["contact"]
        pid=a["id"]
        patched=self.client.patch("/emoi/v2/contacts/"+pid,headers=self.h,json={
            "name":"重命名","model_route":"private-model-name",
            "memory_namespace":"contact:other", "desire_namespace":"desire:other"})
        self.assertEqual(patched.status_code,200,patched.text)
        obj=patched.json()["contact"]
        self.assertEqual(obj["memory_namespace"],a["memory_namespace"])
        self.assertEqual(obj["desire_namespace"],a["desire_namespace"])
        self.assertEqual(obj["name"],"重命名")
        self.assertFalse(obj["memory_connected"])
        self.assertFalse(obj["desire_connected"])

    def test_message_nonce_idempotent_and_not_spoofable_as_ai(self):
        p=self.create("私人")["conversation_id"]
        url="/emoi/v2/conversations/"+p+"/messages"
        body={"text":"保存我自己的输入","nonce":"n"+uuid4().hex,"author":"contact","delivery":"delivered"}
        a=self.post(url,body)
        b=self.post(url,body)
        self.assertEqual(a.status_code,200,a.text)
        self.assertTrue(b.json()["already_saved"])
        self.assertEqual(a.json()["message"]["author"],"human")
        self.assertEqual(a.json()["message"]["delivery"],"stored_not_delivered")
        self.assertEqual(len(self.client.get(url,headers=self.h).json()["messages"]),1)

    def test_media_messages_round_trip_and_preserve_conversation_isolation(self):
        direct = self.create("甲")
        other = self.create("乙")
        url = "/emoi/v2/conversations/" + direct["conversation_id"] + "/messages"
        remote = "/emoi/v2/conversations/" + other["conversation_id"] + "/messages"
        for kind, suffix, mime in [
            ("image", "jpg", "image/jpeg"), ("sticker", "gif", "image/gif"),
            ("voice", "m4a", "audio/mp4"),
        ]:
            stored = "att-" + uuid4().hex[:14] + "." + suffix
            (self.uploads / stored).write_bytes(b"test media bytes")
            body = {"attachment": {"id": stored, "kind": kind, "url": "https://invalid.example"},
                    "nonce": uuid4().hex}
            response = self.post(url, body)
            self.assertEqual(response.status_code, 200, response.text)
            attachment = response.json()["message"]["attachment"]
            self.assertEqual((attachment["kind"], attachment["mime"]), (kind, mime))
            self.assertEqual(attachment["url"], "/uploads/" + stored)
            self.assertTrue(self.post(url, body).json()["already_saved"])
        invalid = {"attachment": {"id": stored, "kind": "image"}, "nonce": uuid4().hex}
        self.assertEqual(self.post(url, invalid).status_code, 422)
        rows = self.client.get(url, headers=self.h).json()["messages"]
        self.assertEqual([row["attachment"]["kind"] for row in rows], ["image", "sticker", "voice"])
        self.assertEqual(self.client.get(remote, headers=self.h).json()["messages"], [])

    def test_location_and_moments_require_owner_and_validate_inputs(self):
        url = "/emoi/v2/moments"
        self.assertEqual(self.client.get(url).status_code, 401)
        ident = str(uuid4())
        self.assertEqual(self.post(url, {"id": ident, "text": "今天见"}).status_code, 200)
        self.assertEqual(self.post(url, {"id": ident, "text": "今天见"}).status_code, 200)
        self.assertEqual(len(self.client.get(url, headers=self.h).json()["posts"]), 1)
        self.assertEqual(self.client.delete(url + "/" + ident, headers=self.h).status_code, 200)
        self.assertEqual(self.client.get(url, headers=self.h).json()["posts"], [])
        cid = self.create("甲")["conversation_id"]
        path = f"/emoi/v2/conversations/{cid}/messages"
        request = {"nonce": uuid4().hex, "attachment": {"kind": "location", "latitude": 31.25, "longitude": 121.5}}
        self.assertEqual(self.post(path, request).json()["message"]["attachment"], request["attachment"])
        request["attachment"]["latitude"] = 95
        self.assertEqual(self.post(path, request).status_code, 422)

    def test_owner_can_publish_a_photo_without_text(self):
        path = "/emoi/v2/moments"
        stored = "att-" + uuid4().hex[:14] + ".png"
        (self.uploads / stored).write_bytes(b"test photo")
        result = self.post(path, {"id": str(uuid4()), "photo_id": stored})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["post"]["attachment"]["url"], "/uploads/" + stored)
        self.assertEqual(self.client.get(path, headers=self.h).json()["posts"][0]["text"], "")
        self.assertEqual(self.post(path, {"id": str(uuid4()), "photo_id": "https://example.org/img"}).status_code, 422)

    def test_shared_photos_and_profile_survive_an_edit(self):
        saved = "att-" + uuid4().hex[:14] + ".png"
        (self.uploads / saved).write_bytes(b"image fixture")
        result = self.post("/emoi/v2/contacts", {
            "name": "角色", "profile": {"avatar": saved, "character": saved, "worldbook": "*\n常驻条目"},
        }).json()
        ident = result["contact"]["id"]
        self.assertEqual(result["contact"]["profile"]["avatar"]["url"], "/uploads/" + saved)
        changed = self.client.patch("/emoi/v2/contacts/" + ident, headers=self.h, json={"name":"新名"}).json()
        self.assertEqual(changed["contact"]["profile"], result["contact"]["profile"])
        album = self.post("/emoi/v2/albums", {"name":"人物相册"}).json()
        self.assertEqual(self.client.get("/emoi/v2/albums").status_code, 401)
        response = self.post(f'/emoi/v2/albums/{album["id"]}/photos', {"id": saved, "contact_id": ident})
        self.assertEqual(response.status_code, 200, response.text)
        photos = self.client.get("/emoi/v2/albums", headers=self.h).json()["photos"]
        self.assertEqual(photos[0]["contact_id"], ident)
        target = f'/emoi/v2/albums/photos/{photos[0]["id"]}'
        self.assertEqual(self.client.patch(target, json={"favorite": True}).status_code, 401)
        self.assertEqual(self.client.patch(target, headers=self.h, json={"favorite": True}).json(), {"favorite": True})
        photos = self.client.get("/emoi/v2/albums", headers=self.h).json()["photos"]
        self.assertTrue(photos[0]["favorite"])

    def test_room_wake_goes_only_to_opted_in_contact(self):
        from backend.emoi_contacts import connect, now, store_wake_message

        profile = {"proactive_enabled": True, "desire_scope": "gpt"}
        bound = self.post("/emoi/v2/contacts", {"name": "指定角色", "profile": profile}).json()
        other = self.create("其他角色")
        duplicate = self.post("/emoi/v2/contacts", {"name": "第二个角色", "profile": profile})
        self.assertEqual(duplicate.status_code, 409)
        with connect(str(Path(self.tmp.name) / "emoi-v2-test.db")) as db:
            self.assertIsNone(store_wake_message(db, "claude", "wake-1", "有人在吗", now()))
            self.assertEqual(store_wake_message(db, "gpt", "wake-1", "有人在吗", now())["title"], "指定角色")
            self.assertIsNone(store_wake_message(db, "gpt", "wake-1", "有人在吗", now()))
        for room, expected in ((bound, 1), (other, 0)):
            rows = self.client.get("/emoi/v2/conversations/" + room["conversation_id"] + "/messages",
                                   headers=self.h).json()["messages"]
            self.assertEqual(len(rows), expected)

    def test_proactive_opt_in_and_event_idempotency(self):
        info = self.create("角色")
        url = "/emoi/v2/contacts/" + info["contact"]["id"]
        payload = {"event_id":"fixture-event", "text":"忙完了", "mode":"video_invite"}
        self.assertEqual(self.post(url + "/proactive", payload).status_code, 403)
        result = self.client.patch(url, headers=self.h, json={"profile":{"proactive_enabled":True}})
        self.assertEqual(result.status_code, 200, result.text)
        sent = self.post(url + "/proactive", payload).json()
        self.assertFalse(sent["duplicate"])
        again = self.post(url + "/proactive", payload).json()
        self.assertEqual(again, {"id": sent["id"], "duplicate": True})
        route = "/emoi/v2/conversations/" + info["conversation_id"] + "/messages"
        rows = self.client.get(route, headers=self.h).json()["messages"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["attachment"], {"kind":"call_invite", "mode":"video"})

    def test_wake_can_ring_and_publish_a_moment_as_the_bound_contact(self):
        from backend.emoi_contacts import connect, now, store_wake_message

        person = self.post("/emoi/v2/contacts", {"name": "角色", "profile": {
            "proactive_enabled": True, "desire_scope": "gpt",
        }}).json()["contact"]
        video = {"contact_id": person["id"], "mode": "video_invite",
                 "attachment": {"kind": "call_invite", "mode": "video"}}
        moment = {"contact_id": person["id"], "mode": "moment"}
        path = str(Path(self.tmp.name) / "emoi-v2-test.db")
        with connect(path) as db:
            notice = store_wake_message(db, "gpt", "fixture-ring", "想打视频", now(), video)
            self.assertIn("视频", notice["body"])
            self.assertIsNotNone(store_wake_message(db, "gpt", "fixture-moment", "出去走走", now(), moment))
            self.assertIsNone(store_wake_message(db, "gpt", "fixture-moment", "出去走走", now(), moment))
        inbox = "/emoi/v2/call-inbox"
        self.assertEqual(self.client.get(inbox).status_code, 401)
        invite = self.client.get(inbox, headers=self.h).json()["invite"]
        self.assertEqual((invite["name"], invite["mode"]), ("角色", "video"))
        answer = self.client.patch(inbox + "/" + invite["id"], headers=self.h, json={"action": "accept"})
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertIsNone(self.client.get(inbox, headers=self.h).json()["invite"])
        rows = self.client.get("/emoi/v2/moments", headers=self.h).json()["posts"]
        self.assertEqual([(row["author"], row["text"]) for row in rows], [("角色", "出去走走")])

    def test_sticker_zip_preserves_group_and_skips_non_images(self):
        import base64
        import io
        from zipfile import ZipFile

        archive = io.BytesIO()
        image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jX1YAAAAASUVORK5CYII=")
        with ZipFile(archive, "w") as zipped:
            zipped.writestr("亲亲/小猫.png", image)
            zipped.writestr("__MACOSX/ignored.png", image)
            zipped.writestr("README.txt", "说明")
        route = "/emoi/v2/stickers/unpack"
        self.assertEqual(self.client.post(route, content=archive.getvalue()).status_code, 401)
        response = self.client.post(route, headers=self.h, content=archive.getvalue())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["stickers"], [{
            "name": "小猫.png", "pack": "亲亲", "mime": "image/png",
            "data": base64.b64encode(image).decode("ascii"),
        }])

    def test_contact_can_switch_between_named_api_and_subscription(self):
        named = "api:" + uuid4().hex
        new = self.post("/emoi/v2/contacts", {"name": "测试", "model_route": named}).json()
        path = "/emoi/v2/contacts/" + new["contact"]["id"]
        chat = "/emoi/v2/conversations/" + new["conversation_id"] + "/messages"
        bindings = []
        real_client = httpx.AsyncClient

        def reply(request):
            import json
            bindings.append(json.loads(request.content)["route"])
            return httpx.Response(200, json={"text": "你好"})

        with patch("backend.emoi_contacts.httpx.AsyncClient", side_effect=lambda **kwargs:
                   real_client(transport=httpx.MockTransport(reply), **kwargs)):
            self.assertTrue(self.post(chat, {"text": "第一次", "nonce": uuid4().hex}).json()["model_dispatched"])
            update = self.client.patch(path, headers=self.h, json={"model_route": "chatgpt-plan"})
            self.assertEqual(update.json()["contact"]["model_route"], "chatgpt-plan")
            self.assertTrue(self.post(chat, {"text": "第二次", "nonce": uuid4().hex}).json()["model_dispatched"])
        self.assertEqual(bindings, [named, "chatgpt-plan"])

    def test_worldbooks_trigger_globally_or_for_bound_contact(self):
        url = "/emoi/v2/worldbooks"

        def entry(text, *, always=False, enabled=True, keys="灯塔"):
            return {"text": text, "keys": keys, "always": always, "enabled": enabled}

        def book(name, entries, *, global_=False, enabled=True):
            response = self.post(url, {"name": name, "entries": entries, "is_global": global_, "enabled": enabled})
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()["book"]["id"]

        shared = book("公共", [entry("公共规则", always=True), entry("彩色灯塔"), entry("停用条目", always=True, enabled=False)], global_=True)
        personal = book("个人", [entry("私有规则", always=True)])
        book("停用书", [entry("停用内容", always=True)], global_=True, enabled=False)
        self.assertEqual(self.client.get(url).status_code, 401)
        first = self.post("/emoi/v2/contacts", {"name": "甲", "model_route": "gpt",
                              "profile": {"worldbook_ids": [shared, personal]}}).json()
        second = self.post("/emoi/v2/contacts", {"name": "乙", "model_route": "gpt"}).json()
        captured = []
        real_client = httpx.AsyncClient

        def reply(request):
            import json
            captured.append(json.loads(request.content)["worldbooks"])
            return httpx.Response(200, json={"text": "收到"})

        with patch("backend.emoi_contacts.httpx.AsyncClient", side_effect=lambda **kwargs:
                   real_client(transport=httpx.MockTransport(reply), **kwargs)):
            for contact, text in ((first, "去看灯塔"), (second, "出门")):
                chat = "/emoi/v2/conversations/" + contact["conversation_id"] + "/messages"
                self.post(chat, {"nonce": uuid4().hex, "text": text})
        self.assertEqual(captured[0].count("公共规则"), 1)
        self.assertIn("彩色灯塔", captured[0])
        self.assertIn("私有规则", captured[0])
        self.assertIn("公共规则", captured[1])
        for word in ("停用条目", "停用内容", "私有规则", "彩色灯塔"):
            self.assertNotIn(word, captured[1])
        self.assertEqual(self.client.delete(url + "/" + personal, headers=self.h).status_code, 200)
        rows = self.client.get("/emoi/v2/contacts", headers=self.h).json()["contacts"]
        updated = next(row for row in rows if row["id"] == first["contact"]["id"])
        self.assertEqual(updated["profile"]["worldbook_ids"], [shared])

    def test_call_reply_lookup_returns_only_the_requested_turn(self):
        new = self.post("/emoi/v2/contacts", {"name": "联系人", "model_route": "gpt"}).json()
        chat = "/emoi/v2/conversations/" + new["conversation_id"] + "/messages"
        call_modes = []
        real_client = httpx.AsyncClient

        def reply(request):
            import json
            call_modes.append(json.loads(request.content)["call_mode"])
            return httpx.Response(200, json={"text": "收到"})

        with patch("backend.emoi_contacts.httpx.AsyncClient", side_effect=lambda **kwargs:
                   real_client(transport=httpx.MockTransport(reply), **kwargs)):
            first = self.post(chat, {"text": "通话", "nonce": uuid4().hex, "call_mode": "voice"}).json()
            self.post(chat, {"text": "后续聊天", "nonce": uuid4().hex})
        result = self.client.get(chat, headers=self.h, params={"reply_to": first["message"]["id"]}).json()
        self.assertEqual(call_modes, ["voice", ""])
        self.assertEqual([row["text"] for row in result["messages"]], ["通话", "收到"])
        self.assertFalse(result["replying"])

    def test_group_replies_are_ordered_isolated_and_idempotent(self):
        a = self.post("/emoi/v2/contacts", {"name":"甲","notes":"甲的私有档案","model_route":"gpt"}).json()
        b = self.post("/emoi/v2/contacts", {"name":"乙","notes":"乙的私有档案","model_route":"claude"}).json()
        direct = "/emoi/v2/conversations/" + a["conversation_id"] + "/messages"
        payloads = []

        def reply(request):
            import json
            data = json.loads(request.content)
            payloads.append(data)
            return httpx.Response(200, json={"text": data["name"] + "的回复"})

        real_client = httpx.AsyncClient
        with patch("backend.emoi_contacts.httpx.AsyncClient", side_effect=lambda **kwargs:
                   real_client(transport=httpx.MockTransport(reply), **kwargs)):
            self.post(direct, {"text":"私聊独有内容","nonce":uuid4().hex})
            payloads.clear()
            members = [a["contact"]["id"], b["contact"]["id"]]
            group = self.post("/emoi/v2/conversations", {"title":"测试群","members":members}).json()["conversation"]
            url = "/emoi/v2/conversations/" + group["id"] + "/messages"
            message = {"text":"群聊问候","nonce":uuid4().hex}
            self.assertTrue(self.post(url, message).json()["model_dispatched"])
            self.assertTrue(self.post(url, message).json()["already_saved"])

        self.assertEqual([data["route"] for data in payloads], ["gpt","claude"])
        self.assertEqual([row["text"] for row in payloads[1]["history"]], ["群聊问候","甲的回复"])
        self.assertEqual([data["notes"] for data in payloads], ["甲的私有档案","乙的私有档案"])
        result = self.client.get(url, headers=self.h).json()
        self.assertFalse(result["replying"])
        self.assertEqual([row["contact_id"] for row in result["messages"]], [None,*members])
        self.assertEqual(result["messages"][0]["delivery"], "replied")


if __name__ == "__main__":
    unittest.main()
