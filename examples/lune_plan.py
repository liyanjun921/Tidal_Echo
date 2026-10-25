"""ChatGPT plan Responses adapter and owner-proxied connection routes."""
import asyncio
import json

import httpx
from fastapi import HTTPException, Request

from lune_auth import PlanError, PlanStore, RESOURCE, start_login


def failure(status, code=""):
    if code in {"subscription_sharing_usage_limit_exceeded", "subscription_sharing_usage_unavailable"} or status == 429:
        return PlanError(429, "ChatGPT 订阅额度暂不可用或已到上限；请到 ChatGPT 设置查看用量。没有切换到 API。", code or "usage_limit")
    if status in {401, 403}:
        return PlanError(status, "ChatGPT 订阅授权失效或没有此模型权限，请重新授权或选择可用模型。没有切换到 API。", code or "access_denied")
    return PlanError(status or 502, "ChatGPT 订阅请求未完成，请检查连接、模型与订阅状态。没有切换到 API。", code or "inference_failed")


def response_body(model, messages, tools):
    inputs, instructions = [], []
    for message in messages:
        role, content = message.get("role"), message.get("content")
        if role in {"system", "developer"}:
            instructions.append(str(content or ""))
        elif role == "tool":
            inputs.append({"type": "function_call_output", "call_id": message["tool_call_id"], "output": str(content or "")})
        elif message.get("responses_items") is not None:
            inputs.extend(message["responses_items"])
        else:
            if content:
                if isinstance(content, str):
                    parts = [{"type": "output_text" if role == "assistant" else "input_text", "text": content}]
                else:
                    parts = []
                    for part in content:
                        if part.get("type") == "text":
                            parts.append({"type": "input_text", "text": part["text"]})
                        elif part.get("type") == "image_url":
                            image = part["image_url"]
                            parts.append({"type": "input_image", "image_url": image["url"], **({"detail": image["detail"]} if image.get("detail") else {})})
                inputs.append({"role": role, "content": parts})
            for call in message.get("tool_calls", []):
                fn = call["function"]
                inputs.append({"type": "function_call", "call_id": call["id"], "name": fn["name"], "namespace": "lune", "arguments": fn["arguments"]})
    body = {"model": model, "input": inputs, "instructions": "\n\n".join(instructions), "store": False, "stream": True, "include": ["reasoning.encrypted_content"]}
    if tools:
        functions = []
        for tool in tools:
            if tool.get("type") != "function":
                raise PlanError(422, "订阅模式只支持本机执行的函数工具")
            fn = tool["function"]
            functions.append({"type": "function", "name": fn["name"], "description": fn.get("description", ""), "parameters": fn.get("parameters", {"type": "object", "properties": {}}), "strict": False})
        body["tools"] = [{"type": "namespace", "name": "lune", "description": "User-authorized tools of the current Luné room; executed by this private server.", "tools": functions}]
    return body


async def events(response):
    data = []
    async for line in response.aiter_lines():
        if not line:
            if data:
                yield "\n".join(data)
                data = []
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    if data:
        yield "\n".join(data)


async def models(store=None):
    store = store or PlanStore()
    auth = await asyncio.to_thread(store.access)
    try:
        async with httpx.AsyncClient(timeout=30, trust_env=True) as client:
            response = await client.get(RESOURCE + "/models", headers={"Authorization": "Bearer " + auth["access_token"]})
        if response.status_code >= 300:
            raise failure(response.status_code)
        rows = response.json().get("models", [])
        return {"account_id": auth["account_id"], "models": [{"id": r["slug"], "name": r.get("display_name", r["slug"])} for r in rows if r.get("visibility") == "list" and isinstance(r.get("slug"), str)]}
    except PlanError:
        raise
    except Exception:
        raise PlanError(503, "ChatGPT 可用模型暂时无法读取") from None


async def chat(route, messages, tools, sink=None, store=None, gate=None):
    store = store or PlanStore()
    auth = await asyncio.to_thread(store.access)
    if not route.get("model"):
        raise PlanError(422, "请先从 ChatGPT 账户可用模型中选择一个模型")
    if gate:
        gate()
    body = response_body(route["model"], messages, tools)
    parts, terminal = [], None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=30), trust_env=True) as client:
            async with client.stream("POST", RESOURCE + "/responses", headers={"Authorization": "Bearer " + auth["access_token"], "Content-Type": "application/json"}, json=body) as response:
                if response.status_code >= 300:
                    raise failure(response.status_code)
                async for raw in events(response):
                    if gate:
                        gate()
                    if raw == "[DONE]":
                        break
                    event = json.loads(raw)
                    kind = event.get("type")
                    if kind == "response.output_text.delta":
                        delta = event.get("delta", "")
                        parts.append(delta)
                        if sink:
                            await sink(delta)
                    elif kind in {"response.failed", "response.incomplete", "error"}:
                        error = event.get("response", {}).get("error") or event.get("error") or event
                        raise failure(429 if "usage" in str(error.get("code", "")) else 502, error.get("code", ""))
                    elif kind == "response.completed":
                        terminal = event.get("response", {})
                        if terminal.get("status") != "completed":
                            raise failure(502, "not_completed")
                        break
        if terminal is None:
            raise failure(502, "stream_interrupted")
        output = terminal.get("output", [])
        calls = []
        allowed = {t["function"]["name"] for t in tools or []}
        for item in output:
            if item.get("type") == "function_call":
                name = item.get("name", "")
                if name.startswith("lune."):
                    name = name[5:]
                if name not in allowed or item.get("namespace", "lune") != "lune":
                    raise PlanError(422, "模型请求了本轮未授权的工具")
                calls.append({"id": item["call_id"], "name": name, "arguments": item.get("arguments", "{}")})
        text = "".join(parts)
        if not text:
            text = "".join(p.get("text", "") for item in output if item.get("type") == "message" for p in item.get("content", []) if p.get("type") == "output_text")
            if text and sink:
                await sink(text)
        return {"text": text.strip(), "thinking": "", "tool_calls": calls, "usage": terminal.get("usage", {}), "responses_items": output, "billing_mode": "chatgpt_plan"}
    except PlanError:
        raise
    except asyncio.CancelledError:
        raise
    except Exception:
        raise failure(503, "connection_failed") from None


def register(app):
    def error(e):
        return HTTPException(e.status, e.message)

    async def object_body(request):
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(422, "请求格式不正确")
        if not isinstance(body, dict):
            raise HTTPException(422, "请求格式不正确")
        return body

    @app.get("/loop/subscriptions")
    async def status():
        from lune_claude import enabled, command, pool
        import shutil
        installed = bool(shutil.which(command()[0]))
        return {"chatgpt": await asyncio.to_thread(PlanStore().status), "claude": {
            "ready": False, "state": "needs_account_test" if enabled() and installed else "runtime_required",
            "transport": "claude_code_stream_json", "runtime_enabled": enabled(), "installed": installed,
            "running": any(s.proc and s.proc.returncode is None for s in pool.sessions.values()),
            "message": "官方 Claude Code 常驻桥接已接线。请在运行电脑安装并登录 CLI、启用运行端后测试；Luné 不导入 Claude 令牌，也不自动改用 API。",
            "docs_url": "https://code.claude.com/docs/en/cli-reference"}}

    @app.post("/loop/subscriptions/chatgpt/start")
    async def login(request: Request):
        body = await object_body(request)
        try:
            return await asyncio.to_thread(start_login, PlanStore(), body.get("account_id"))
        except PlanError as e:
            raise error(e)

    @app.post("/loop/subscriptions/chatgpt/import")
    async def import_connection(request: Request):
        raw = await request.body()
        if len(raw) > 100000:
            raise HTTPException(413, "订阅连接文件过大")
        try:
            return await asyncio.to_thread(PlanStore().import_session, json.loads(raw))
        except PlanError as e:
            raise error(e)
        except (ValueError, TypeError):
            raise HTTPException(422, "订阅连接文件格式不正确")

    @app.post("/loop/subscriptions/chatgpt/select")
    async def select(request: Request):
        try:
            return await asyncio.to_thread(PlanStore().select, (await object_body(request)).get("account_id"))
        except PlanError as e:
            raise error(e)

    @app.post("/loop/subscriptions/chatgpt/signout")
    async def signout(request: Request):
        try:
            return await asyncio.to_thread(PlanStore().sign_out, (await object_body(request)).get("account_id"))
        except PlanError as e:
            raise error(e)

    @app.get("/loop/subscriptions/chatgpt/models")
    async def model_list():
        try:
            return await models()
        except PlanError as e:
            raise error(e)
