"""Synthetic provider for offline E2E verification; never contacts real models."""
import asyncio
import json
import os
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, Response

app = FastAPI()


@app.post("/v1/text-to-speech/{voice_id}")
async def speech(voice_id: str, request: Request):
    body = await request.json()
    assert request.headers.get("xi-api-key") == "synthetic-voice-key"
    assert voice_id == "fixture_voice" and body["model_id"] == "eleven_multilingual_v2"
    assert request.query_params["output_format"] == "mp3_44100_128"
    return Response(b"ID3synthetic-elevenlabs", media_type="audio/mpeg")


@app.post("/v1/t2a_v2")
async def minimax(request: Request):
    body = await request.json()
    assert request.headers.get("Authorization") == "Bearer synthetic-voice-key"
    assert body["voice_setting"]["voice_id"] == "fixture_voice" and body["model"] == "speech-02-hd"
    return {"data": {"audio": b"ID3synthetic-minimax".hex()}}


def record(body):
    with open(os.environ["LUNE_TEST_REQUESTS"], "a") as f:
        f.write(json.dumps(body) + "\n")


@app.post("/v1/chat/completions")
async def openai(request: Request):
    body = await request.json()
    record(body)
    reply = "TEST_GPT：消息已经过测试服务保存。"
    tool_name = next((t["function"]["name"] for t in body.get("tools", []) if t["function"]["name"].endswith("__echo")), None)
    last_user = next((m["content"] for m in reversed(body["messages"]) if m["role"] == "user"), "")
    system = str(body['messages'][0].get('content', ''))
    if not body.get('tools') and '【LUNE_WREN_WAKE】' in str(last_user):
        assert any('系统本轮自动装配的 Room 状态' in str(m.get('content', '')) for m in body['messages'])
        return {'choices':[{'message':{'content':json.dumps({'action':'say','text':'WREN_WAKE_DELIVERED：那本小书慢慢做。'},ensure_ascii=False)}}], 'usage':{'prompt_tokens':31,'completion_tokens':12}}
    if not body.get('tools') and '【LUNE_CHECKLIST_ALARM】' in str(last_user):
        return {'choices':[{'message':{'content':json.dumps({'action':'say','text':'CHECKLIST_ALARM_DELIVERED：到时间了，我们一起看看清单。'},ensure_ascii=False)}}], 'usage':{'prompt_tokens':18,'completion_tokens':14}}
    if not body.get('tools') and '【LUNE_CINEMA_TICK】' in str(last_user):
        return {'choices':[{'message':{'content':json.dumps({'action':'say','text':'CINEMA_GUEST_DELIVERED：刚才这段转场很有意思。'},ensure_ascii=False)}}], 'usage':{'prompt_tokens':22,'completion_tokens':15}}
    if not body.get('tools') and '【LUNE_FOLIO_' in system:
        result={'name':'Folio精修标题','summary':'FOLIO_REFINED_SUMMARY','narrative':'FOLIO_MOOD_NARRATIVE','tags':['测试'],'domain':['日常'],'valence':.7,'arousal':.4,'importance':6,'content':'FOLIO_REFINED_BODY'}
        return {'choices':[{'message':{'content':json.dumps(result,ensure_ascii=False)}}]}
    if not body.get('tools') and ('Duet 独立日记' in str(last_user) or '提取本房间真正没聊完' in str(last_user)):
        reply = 'SYNTHETIC_INDEPENDENT_DIARY' if 'Duet 独立日记' in str(last_user) else 'PASS'
        return {'choices': [{'message': {'content': reply}}]}
    if not body.get('tools') and 'valence' in system and 'arousal' in system:
        return {'choices': [{'message': {'content': json.dumps({'name': '合成记忆', 'tags': ['测试'], 'domain': ['日常'], 'valence': .7, 'arousal': .4, 'why_remembered': '这是合成测试原话。'}, ensure_ascii=False)}}]}
    if body["messages"][0].get("content", "").startswith("严格按整理任务"):
        import re
        prompt = str(last_user)
        if "事实拆条" in prompt:
            reply = json.dumps({"fact": "用户说自己喜欢蓝色鸢尾。", "tag": "life", "kind": "state"}, ensure_ascii=False)
        elif '只输出 JSON 对象 {"items"' in prompt:
            batch = json.loads(prompt[prompt.rfind("\n[") + 1:])
            reply = json.dumps({"items": [{"block": item["block"], "facts": []} for item in batch]})
        else:
            day = re.search(r"# 对话整理 · (\d{4}-\d{2}-\d{2})", prompt).group(1)
            reply = "# 对话整理 · " + day + "\n用户说自己喜欢蓝色鸢尾。\n当下状态：这段对话已经结束，偏好按原话记录。"
        assert not body.get("tools"), "archive model must have no tools"
        return {"choices": [{"message": {"content": reply}}]}
    wants_tool = "TOOL_UI_MARKER" in str(last_user) and not any(m["role"] == "tool" for m in body["messages"])
    arguments = '{"value":"echo fixture"}'
    if body.get('tools') and 'LIVING_WRITE_TRIGGER' in str(last_user):
        assert {'today_set','today_get','ctx_set','ctx_get','ctx_drop'} <= {t['function']['name'] for t in body['tools']}
        count=sum(m['role']=='tool' for m in body['messages'])
        sequence=[('today_set',{'items':[{'key':'晚饭','value':'今天晚饭吃了青菜'}],'quote':'我今天晚饭吃了青菜。'}),
                  ('ctx_set',{'key':'家人来访','value':'妈妈现在还在我这里，准备下周回家','ttl_days':14,'quote':'妈妈准备下周回家，现在还在我这里。'}),
                  ('today_get',{}),('ctx_get',{})]
        if count<len(sequence):
            wants_tool,tool_name=True,sequence[count][0]
            arguments=json.dumps(sequence[count][1],ensure_ascii=False)
    if body.get('tools') and 'LIVING_DROP_TRIGGER' in str(last_user) and not any(m['role']=='tool' for m in body['messages']):
        wants_tool,tool_name=True,'ctx_drop'
        arguments=json.dumps({'key':'家人来访','quote':'妈妈今天已经回家了。'},ensure_ascii=False)
    if body.get('tools') and 'XC_BOX_TRIGGER' in str(last_user) and not any(m['role']=='tool' for m in body['messages']):
        wants_tool,tool_name=True,'xinchao_box'
        arguments=json.dumps({'action':'put','kind':'secret','text':'XC_SECRET_ACTUAL_TOOL_RESULT','title':'XC_PRIVATE_TITLE'},ensure_ascii=False)
    if body.get('tools') and 'DESIRE_TOOL_TRIGGER' in str(last_user):
        count=sum(m['role']=='tool' for m in body['messages'])
        if count==0:
            wants_tool,tool_name=True,'lune_workspace'
            arguments=json.dumps({'action':'create','kind':'journal','scope':'gpt','title':'DESIRE_ACTUAL_WRITE','content':'这是由测试模型真实调用宿主保存的日记。','data':{}},ensure_ascii=False)
        elif count==1:
            import sqlite3
            with sqlite3.connect(os.environ['RELAY_DB']) as db:
                memory_id=db.execute("SELECT id FROM lune_wren_thoughts WHERE scope='gpt' AND visibility='shared' ORDER BY updated DESC LIMIT 1").fetchone()[0]
            wants_tool,tool_name=True,'lune_room'
            arguments=json.dumps({'action':'experience','source_memory_id':memory_id,'content':'DESIRE_REAL_E：我认真地把那本小书的念头留了下来。','valence':.6,'arousal':.5,'tension':.1,'response_tendency':'engage','growth_delta':'growth','priority':85,'visibility':'shared'},ensure_ascii=False)
    if body.get('tools') and 'WREN_TOOL_TRIGGER' in str(last_user) and not any(m['role']=='tool' for m in body['messages']):
        import sqlite3
        with sqlite3.connect(os.environ['RELAY_DB']) as db:
            source = db.execute("SELECT id FROM messages WHERE direction='in' AND text LIKE '%WREN_TOOL_TRIGGER%' ORDER BY id DESC LIMIT 1").fetchone()[0]
        assert any(t['function']['name']=='lune_room' for t in body['tools'])
        wants_tool, tool_name = True, 'lune_room'
        arguments = json.dumps({'action':'thought','source_id':source,'quote':'海边那本小书','drive':'craft','visibility':'shared'},ensure_ascii=False)
    if 'OMBRE_WRITE_TRIGGER' in str(last_user) and not any(m['role'] == 'tool' for m in body['messages']):
        wants_tool, tool_name = True, 'ombre_hold'
        arguments = json.dumps({'content': 'OMBRE_PRIVATE_MARKER 用户说我们周日去海边看蓝色风筝。', 'title': 'Ombre真实工具接线', 'valence': .8, 'arousal': .5})
    if "WORKSPACE_TRIGGER" in str(last_user) and not any(m["role"] == "tool" for m in body["messages"]):
        wants_tool, tool_name = True, "lune_workspace"
        arguments = json.dumps({"action": "create", "kind": "todo", "scope": "group", "title": "HTTP_TOOL_SAVED", "content": "Synthetic tool verification", "data": {"owner": "gpt", "done": False}})
    if "MEMORY_WRITE_TRIGGER" in str(last_user) and not any(m["role"] == "tool" for m in body["messages"]):
        wants_tool, tool_name = True, "lune_memory"
        arguments = json.dumps({"action": "remember", "quote": "我喜欢蓝色鸢尾。", "title": "HTTP_MEMORY_SAVED"})
    if "NATIVE_WRITE_TRIGGER" in str(last_user) and not any(m["role"] == "tool" for m in body["messages"]):
        wants_tool, tool_name = True, "latent_append"
        arguments = json.dumps({"text": "用户说想周六去海边看风筝。", "current_state": "只是计划，尚未成行。",
            "indexEvidence": [{"type": "event", "quote": "用户说想周六去海边看风筝。"}, {"type": "state", "quote": "只是计划，尚未成行。"}],
            "unresolvedOps": [{"action": "none"}]})
    if any(m["role"] == "tool" for m in body["messages"]):
        reply = "TEST_GPT：TOOL_RESULT_MARKER 工具结果已收到。"
    if not body.get("stream"):
        return {"choices": [{"message": {"content": reply}}]}
    async def events():
        if wants_tool and tool_name:
            yield "data: " + json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "fixture-call", "type": "function", "function": {"name": tool_name, "arguments": arguments}}]}}]}) + "\n\n"
            yield 'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\ndata: [DONE]\n\n'
            return
        for chunk in (reply[:9], reply[9:]):
            yield "data: " + json.dumps({"choices": [{"delta": {"content": chunk}}]}) + "\n\n"
            await asyncio.sleep(.15)
        yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/v1/messages")
async def anthropic(request: Request):
    body = await request.json()
    record(body)
    reply = "TEST_CLAUDE：已看到群聊里前一位成员的回复。"
    if not body.get("stream"):
        return {"content": [{"type": "text", "text": reply}], "usage": {"input_tokens": 1, "output_tokens": 1}}
    async def events():
        for event in ({"type": "message_start", "message": {"usage": {"input_tokens": 1}}}, {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": reply}}, {"type": "message_delta", "usage": {"output_tokens": 1}}, {"type": "message_stop"}):
            yield "data: " + json.dumps(event) + "\n\n"
            await asyncio.sleep(.15)
    return StreamingResponse(events(), media_type="text/event-stream")
