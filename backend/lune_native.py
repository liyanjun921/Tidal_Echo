"""Authenticated full Latent workspace, native MCP tools, and durable job runner."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
import signal
from pathlib import Path
import sqlite3
import sys
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

try:
    from .lune_memory import LatentEngine, MemoryStore, room_view, view_scopes
except ImportError:
    from lune_memory import LatentEngine, MemoryStore, room_view, view_scopes

PRODUCT_FEATURES = [
    ("tools", "八个原生记忆工具", "原版 MCP 处理器；房间范围与来源写保护"),
    ("passive", "原版自动浮现", "块模式与事实模式、临时宿主、冷却与失效检查"),
    ("facts", "事实回填与增量事实", "status / next / submit / finish、原版校验及去重"),
    ("archive", "后台自动落档", "原版批次、自审、形状闸、游标、失败重试与状态"),
    ("persona", "人格初始化与编译", "原版九步流程、来源证据、逐节确认；空白或原文直用均保留"),
    ("imports", "历史导入", "ChatGPT、Claude、项目、记忆导出、聊天文本、Markdown"),
    ("hut", "山屋的全部数据入口", "磁带、事实簿、浮冰、石堆、拍立得、火漆信、地图、护照、天气、小锁信"),
    ("notes", "便条与模型回信", "原版 NoteStore、开场递送和 latent_note_reply"),
    ("routes", "三条检索路线", "零依赖、本地语义、可选云端；默认本地，云端须单独选择"),
    ("doctor", "部署诊断", "原版只读 doctor、索引状态、事实与未解决项统计"),
    ("continuation", "上下文续接", "API 消息投影先落档和检查点；Claude Code 原版 forge 供本地连接端"),
    ("backup", "原生档案备份", "完整私有语料、人格、事实、便条、收尾和后台账本"),
]
READ_TOOLS = {"latent_search", "latent_session_start"}
NATIVE_TOOLS = READ_TOOLS | {"latent_append", "latent_supersede", "latent_correct", "latent_cleanup",
    "latent_unresolved", "latent_thread_close", "latent_fact_backfill", "latent_note_reply"}


def full_root(path):
    return Path(os.environ.get("LUNE_LATENT_FULL_DIR") or Path(path).resolve().parent / "lune-private" / "latent-full")


def init(path):
    with sqlite3.connect(path) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS lune_native_jobs
            (id TEXT PRIMARY KEY,view TEXT,kind TEXT,state TEXT,created_at TEXT,result TEXT)""")
        c.execute("UPDATE lune_native_jobs SET state='interrupted' WHERE state IN ('queued','running')")


class NativeEngine:
    def __init__(self, path):
        self.engine = LatentEngine(path)
        self.store = self.engine.store

    @property
    def root(self):
        return full_root(self.store.path)

    async def call(self, view, action, **values):
        view_scopes(view)
        records = self.engine.snapshot(view)
        result = await self.engine.worker({"operation": "full", "action": action, "view": view,
            "records": records, "full_root": str(self.root), "embedding_route": self.store.config()["embedding_route"],
            "model_cache": str(self.engine.model_cache()), **values})
        if action == "context" and [(r["id"], r["version"], r["status"]) for r in records] != [
                (r["id"], r["version"], r["status"]) for r in self.engine.snapshot(view)]:
            raise RuntimeError("memory_changed")
        return result

    async def context(self, view, query, agent, opening, delivery_id, before_id=None):
        tail = {}
        if opening and before_id:
            with self.store.db() as c:
                rows = c.execute("SELECT ts,direction,text,meta FROM messages WHERE id<? AND json_extract(meta,'$.api_session')=? AND kind IN ('user','reply','text') ORDER BY id DESC LIMIT 6", (before_id, "lune-" + view)).fetchall()
            rows = [r for r in reversed(rows) if r["text"] and not json.loads(r["meta"]).get("date_unknown")]
            if rows:
                tail = {"tail": [("用户" if r["direction"] == "in" else "AI", r["text"]) for r in rows],
                    "tail_start": datetime.fromisoformat(rows[0]["ts"]).timestamp(),
                    "tail_end": datetime.fromisoformat(rows[-1]["ts"]).timestamp()}
        return await self.call(view, "context", query=query, opening=opening,
            delivery_id=delivery_id, session_id=view + ":" + agent, auto_recall=self.store.config()["auto_recall"], **tail)

    async def rpc(self, view, message, *, model=False):
        if not isinstance(message, dict) or message.get("method") not in {
                "initialize", "notifications/initialized", "tools/list", "tools/call", "ping"}:
            raise HTTPException(422, "不是允许的 MCP 请求")
        if message.get("method") == "tools/call":
            if not isinstance(message.get("params"), dict):
                raise HTTPException(422, "MCP params 必须是对象")
            name = message["params"].get("name")
            if not isinstance(name, str) or name not in NATIVE_TOOLS:
                return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32601, "message": "未知工具"}}
            if model and name not in READ_TOOLS and not self.store.config()["model_writes"]:
                raise HTTPException(403, "已关闭模型记忆写入")
        return (await self.call(view, "rpc", message=message))["rpc"]

    def transcript(self, view):
        """Export actual spoken messages only, never host memory or tool results."""
        if view == "shared":
            raise HTTPException(422, "共享不是聊天房间，不能合并私聊进行落档")
        directory = self.root / view
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / "conversation.jsonl"
        with self.store.db() as c:
            rows = c.execute("SELECT * FROM messages WHERE json_extract(meta,'$.api_session')=? ORDER BY id", ("lune-" + view,)).fetchall()
        lines = []
        for row in rows:
            meta = json.loads(row["meta"])
            if not row["text"] or (row["direction"] == "out" and row["kind"] != "reply") or meta.get("error") or meta.get("api", {}).get("error") or meta.get("date_unknown"):
                continue
            text = row["text"]
            if view == "group" and row["direction"] == "out":
                text = "[群聊成员 " + str(meta.get("agent_id") or "AI") + "] " + text
            lines.append(json.dumps({"id": str(row["id"]), "ts": row["ts"],
                "role": "user" if row["direction"] == "in" else "assistant", "text": text}, ensure_ascii=False))
        temp = directory / (".conversation-" + uuid.uuid4().hex)
        temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(temp, 0o600)
        temp.replace(path)
        return path


def register(app, relay):
    path = relay["DB_PATH"]
    native = NativeEngine(path)
    tasks, processes = {}, {}

    async def body(request):
        if int(request.headers.get("content-length") or 0) > 12 * 1024 * 1024:
            raise HTTPException(413, "单次资料限制为 12MB")
        raw = await request.body()
        if len(raw) > 12 * 1024 * 1024:
            raise HTTPException(413, "单次资料限制为 12MB")
        try:
            data = json.loads(raw)
        except ValueError:
            raise HTTPException(422, "请提交 JSON")
        if not isinstance(data, dict):
            raise HTTPException(422, "请求必须是对象")
        return data

    def jobs():
        with native.store.db() as c:
            return [dict(r) for r in c.execute("SELECT * FROM lune_native_jobs ORDER BY created_at DESC LIMIT 40")]

    async def execute(jid, view, kind, data):
        with native.store.db() as c:
            c.execute("UPDATE lune_native_jobs SET state='running' WHERE id=?", (jid,))
        env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "TMPDIR"}}
        # Only the explicitly invoked local job bridge receives the owner's relay key.
        env["RELAY_SECRET"] = relay["SECRET"]
        env["LUNE_JOB_RELAY"] = "http://127.0.0.1:" + os.environ.get("PORT", "8080") + "/relay"
        env["LUNE_JOB_LOOP"] = "http://127.0.0.1:3020"
        cfg = native.store.config()
        payload = {"kind": kind, "view": view, "root": str(native.root), "data": data,
            "agent": view if view in {"gpt", "claude"} else cfg["archive_agent"], "facts": cfg["archive_facts"]}
        try:
            if not native.engine.installation():
                raise RuntimeError("请先独立安装固定版本 Latent")
            if kind in {"archive", "flush"}:
                payload["transcript"] = str(native.transcript(view))
            proc = await asyncio.create_subprocess_exec(sys.executable, "-I", "-B",
                str(Path(__file__).with_name("latent_jobs.py")), str(native.engine.source()),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, env=env, start_new_session=True)
            processes[jid] = proc
            stdout, _ = await asyncio.wait_for(proc.communicate(json.dumps(payload, ensure_ascii=False).encode()), 1800)
            result = json.loads(stdout)
            state = "failed" if proc.returncode or result.get("status") in {"failed", "aborted"} else "done"
        except asyncio.CancelledError:
            state, result = "cancelled", {"error": "任务已停止，已落盘记录与原始对话保留"}
            raise
        except Exception as exc:
            state, result = "failed", {"error": "任务未完成（" + type(exc).__name__ + "），未伪造成功；检查模型连接或原版返回"}
        finally:
            proc = processes.pop(jid, None)
            if proc and proc.returncode is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await proc.communicate()
            if "state" in locals():
                with native.store.db() as c:
                    c.execute("UPDATE lune_native_jobs SET state=?,result=? WHERE id=?", (state, json.dumps(result, ensure_ascii=False), jid))
            tasks.pop(jid, None)

    async def start_job(view, kind, data):
        view_scopes(view)
        if kind not in {"archive", "flush", "backfill", "initialize", "import", "backup"}:
            raise HTTPException(422, "不支持的任务")
        if any(r["view"] == view and r["state"] in {"running", "queued"} for r in jobs()):
            raise HTTPException(409, "这个房间已有任务正在进行")
        jid = uuid.uuid4().hex
        with native.store.db() as c:
            c.execute("INSERT INTO lune_native_jobs VALUES(?,?,?,?,?,?)", (jid, view, kind, "queued", datetime.now(timezone.utc).isoformat(), "{}"))
        tasks[jid] = asyncio.create_task(execute(jid, view, kind, data))
        return {"id": jid, "state": "queued"}

    @app.get("/lune/native/status")
    async def status(request: Request):
        relay["check_auth"](request)
        return {"installed": native.engine.installation(), "settings": native.store.config(), "jobs": jobs(),
            "features": [{"id": i, "name": n, "detail": d, "wired": True} for i, n, d in PRODUCT_FEATURES],
            "message": "原版功能已接线；后台模型任务需所选模型连接可用，Claude Code forge 需本地连接端"}

    @app.post("/lune/native/{view}/mcp")
    async def mcp(view: str, request: Request):
        relay["check_auth"](request)
        if not native.store.config()["enabled"] or not native.store.config()["native_full"]:
            raise HTTPException(409, "完整记忆引擎已关闭")
        result = await native.rpc(view, await body(request))
        return Response(status_code=202) if result is None else JSONResponse(result)

    @app.post("/lune/assistant/native")
    async def assistant(request: Request):
        relay["check_auth"](request)
        data = await body(request)
        view = room_view(data.get("room", ""), data.get("agent_id"))
        if not isinstance(data.get("run_id"), str) or not data["run_id"]:
            raise HTTPException(422, "缺少有效回合 ID")
        with native.store.db() as c:
            native.store.gate(c, data)
        if not native.store.config()["enabled"] or not native.store.config()["native_full"]:
            raise HTTPException(409, "完整记忆引擎已关闭")
        return await native.rpc(view, data.get("message"), model=True)

    @app.api_route("/lune/native/{view}/admin/{resource:path}", methods=["GET", "POST"])
    async def admin(view: str, resource: str, request: Request):
        relay["check_auth"](request)
        result = await native.call(view, "admin", path="/" + resource, method=request.method,
            query={k: request.query_params.getlist(k) for k in request.query_params},
            data=await body(request) if request.method == "POST" else {})
        return JSONResponse(result["body"], status_code=result["status"])

    @app.post("/lune/native/{view}/jobs/{kind}")
    async def start(view: str, kind: str, request: Request):
        relay["check_auth"](request)
        return await start_job(view, kind, await body(request))

    @app.post("/lune/native/{view}/prepare-continuation")
    async def prepare_continuation(view: str, request: Request):
        relay["check_auth"](request)
        cfg = native.store.config()
        if not (cfg["enabled"] and cfg["native_full"] and cfg["context_continuation"]):
            raise HTTPException(409, "上下文续接已关闭，不得以此静默裁剪")
        job = await start_job(view, "flush", {})
        task = tasks[job["id"]]
        await asyncio.shield(task)
        row = next(r for r in jobs() if r["id"] == job["id"])
        result = json.loads(row["result"])
        if row["state"] != "done" or result.get("status") != "flushed":
            raise HTTPException(409, "后台落档尚未成功，保留原始上下文，不执行续接")
        checkpoint = (await native.call(view, "checkpoint",
            current_state="（续接检查点，自动生成）原始聊天完整保留，较早对话已按后台游标处理；本窗口继续。",
            topics=["Luné 请求上下文续接"]))["rpc"]
        if checkpoint.get("error") or checkpoint.get("result", {}).get("isError"):
            raise HTTPException(409, "续接检查点未成功，不裁剪")
        return {"ok": True, "cursor_epoch": result["cursor_epoch"], "cursor_keys": result["cursor_keys"], "job": job["id"]}

    @app.post("/lune/native/jobs/{jid}/stop")
    async def stop(jid: str, request: Request):
        relay["check_auth"](request)
        task = tasks.get(jid)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return {"ok": True}

    @app.get("/lune/native/{view}/backup")
    async def backup(view: str, request: Request):
        relay["check_auth"](request)
        view_scopes(view)
        archive = native.root / (view + "-backup.zip")
        if not archive.is_file():
            raise HTTPException(404, "请先运行完整备份任务")
        return FileResponse(archive, filename="lune-latent-" + view + ".zip")

    async def watch():
        while True:
            await asyncio.sleep(600)
            cfg = native.store.config()
            if cfg["enabled"] and cfg["native_full"] and cfg["archive_enabled"] and native.engine.installation():
                for view in ("gpt", "claude", "group"):
                    try:
                        await start_job(view, "archive", {})
                    except HTTPException:
                        pass

    async def shutdown():
        for task in list(tasks.values()):
            task.cancel()
        await asyncio.gather(*list(tasks.values()), return_exceptions=True)

    return {"init": lambda: init(path), "watch": watch, "shutdown": shutdown, "engine": native}
