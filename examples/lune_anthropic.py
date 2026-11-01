"""Translate the loop's neutral messages/tools to Anthropic Messages API.

Reference: https://platform.claude.com/docs/en/build-with-claude/streaming
Only public text is projected; thinking/signature blocks are not promoted to replies.
"""
import json
import httpx


def request_body(route, messages, tools, max_tokens, temperature, stream):
    system, converted = [], []
    for m in messages:
        if m["role"] == "system":
            system.append(str(m["content"]))
            continue
        if m["role"] == "tool":
            role, blocks = "user", [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": str(m["content"])}]
        else:
            role, blocks = m["role"], []
            content = m.get("content") or ""
            if isinstance(content, str) and content:
                blocks.append({"type": "text", "text": content})
            elif isinstance(content, list):
                for p in content:
                    if p.get("type") == "text":
                        blocks.append({"type": "text", "text": p["text"]})
                    elif p.get("type") == "image_url":
                        url = p["image_url"]["url"]
                        if not url.startswith("data:") or ";base64," not in url:
                            raise ValueError("Only controlled inline images are supported")
                        head, data = url.split(";base64,", 1)
                        blocks.append({"type": "image", "source": {"type": "base64", "media_type": head[5:], "data": data}})
            for call in m.get("tool_calls") or []:
                fn = call["function"]
                blocks.append({"type": "tool_use", "id": call["id"], "name": fn["name"], "input": json.loads(fn["arguments"])})
        if not blocks:
            continue
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"].extend(blocks)
        else:
            converted.append({"role": role, "content": blocks})
    out = {"model": route["model"], "max_tokens": max_tokens, "temperature": temperature,
           "messages": converted, "stream": stream}
    if system:
        out["system"] = "\n\n".join(system)
    if tools:
        out["tools"] = [{"name": t["function"]["name"], "description": t["function"].get("description", ""),
                         "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}})} for t in tools]
    return out


async def chat(route, messages, tools, sink, max_tokens, temperature, raise_for, stream=True):
    body = request_body(route, messages, tools, max_tokens, temperature, stream)
    base = route["url"].rstrip("/")
    url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
    headers = {"x-api-key": route["key"], "anthropic-version": "2023-06-01", "content-type": "application/json"}
    text, calls, usage = [], {}, {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=30), trust_env=True) as client:
        if not stream:
            response = await client.post(url, headers=headers, json=body)
            await raise_for(response, route)
            result = response.json()
            usage = result.get("usage", {})
            for i, block in enumerate(result.get("content", [])):
                if block["type"] == "text":
                    text.append(block["text"])
                if block["type"] == "tool_use":
                    calls[i] = {"id": block["id"], "name": block["name"], "arguments": json.dumps(block["input"])}
        else:
            ended = False
            async with client.stream("POST", url, headers=headers, json=body) as response:
                await raise_for(response, route)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line[5:].strip())
                    kind = event.get("type")
                    if kind == "error":
                        raise RuntimeError("Anthropic streaming error")
                    if kind == "message_start":
                        usage.update(event.get("message", {}).get("usage", {}))
                    if kind == "message_delta":
                        usage.update(event.get("usage", {}))
                    if kind == "content_block_start":
                        b = event.get("content_block", {})
                        if b.get("type") == "tool_use":
                            calls[event["index"]] = {"id": b["id"], "name": b["name"], "arguments": ""}
                    if kind == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            chunk = delta.get("text", "")
                            text.append(chunk)
                            if sink:
                                await sink(chunk)
                        if delta.get("type") == "input_json_delta" and event["index"] in calls:
                            calls[event["index"]]["arguments"] += delta.get("partial_json", "")
                    if kind == "message_stop":
                        ended = True
                if not ended:
                    raise RuntimeError("Anthropic stream ended before completion")
    return {"text": "".join(text), "thinking": "", "tool_calls": [calls[k] for k in sorted(calls)], "usage": usage}
