"""The v2 contact API is a PRIVATE and isolated registry. No fake model delivery."""
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
from backend.emoi_contacts import register


class ContactIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = str(Path(self.tmp.name) / "emoi-v2-test.db")
        self.uploads = Path(self.tmp.name) / "uploads"
        self.uploads.mkdir()
        app = FastAPI()
        def check_auth(request):
            if request.headers.get("authorization") != "Bearer test-only-owner":
                raise HTTPException(401, "unauthorized")
        runtime = register(app, {"DB_PATH":path,"UPLOAD_DIR":self.uploads,"check_auth":check_auth,"loop_base_url":lambda:"http://loop.test"})
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
