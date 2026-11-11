"""The v2 contact API is a PRIVATE and isolated registry. No fake model delivery."""
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from backend.emoi_contacts import register


class ContactIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = str(Path(self.tmp.name) / "emoi-v2-test.db")
        app = FastAPI()
        def check_auth(request):
            if request.headers.get("authorization") != "Bearer test-only-owner":
                raise HTTPException(401, "unauthorized")
        runtime = register(app, {"DB_PATH":path,"check_auth":check_auth})
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
        p=self.create("甲"),q=self.create("乙")
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


if __name__ == "__main__":
    unittest.main()
