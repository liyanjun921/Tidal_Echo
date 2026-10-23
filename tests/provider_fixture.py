"""Synthetic provider for offline E2E verification; never contacts real models."""
import asyncio
import json
import os
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()


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
    wants_tool = "TOOL_UI_MARKER" in str(last_user) and not any(m["role"] == "tool" for m in body["messages"])
    arguments = '{"value":"echo fixture"}'
    if "WORKSPACE_TRIGGER" in str(last_user) and not any(m["role"] == "tool" for m in body["messages"]):
        wants_tool, tool_name = True, "lune_workspace"
        arguments = json.dumps({"action": "create", "kind": "todo", "scope": "group", "title": "HTTP_TOOL_SAVED", "content": "Synthetic tool verification", "data": {"owner": "gpt", "done": False}})
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
