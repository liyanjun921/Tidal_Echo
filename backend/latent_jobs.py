"""Bounded entry points into original Latent utilities; stdin carries private input."""
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
from types import SimpleNamespace
import urllib.request
import uuid
import zipfile


class UTF8Capture(io.StringIO):
    # The original CLI explicitly reconfigures stdout for Windows UTF-8 support.
    def reconfigure(self, **kwargs):
        return None


def generate(prompt, agent):
    endpoint = os.environ["LUNE_JOB_LOOP"] + "/loop/native/generate"
    request = urllib.request.Request(endpoint, json.dumps({"prompt": prompt, "agent": agent}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["RELAY_SECRET"]})
    with urllib.request.urlopen(request, timeout=650) as response:
        return json.load(response)["text"]


def run(p, source):
    from latent_full_worker import locked
    root, view, data = Path(p["root"]), p["view"], p["data"]
    if view not in {"gpt", "claude", "group", "shared"}:
        raise ValueError("view")
    directory, kind = root / view, p["kind"]
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    cfg = SimpleNamespace(url=os.environ["LUNE_JOB_RELAY"] + "/lune/native/" + view + "/mcp",
                          token=os.environ["RELAY_SECRET"])
    import background_archive as ba
    def call(name, args):
        return ba.call_latent(cfg.url, cfg.token, name, args)
    if kind in {"archive", "flush"}:
        from time_context import TimeContext
        model_cmd = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--model", p["agent"]]
        cfg = SimpleNamespace(**vars(cfg), source="jsonl:" + p["transcript"],
            state_dir=str(directory / "archive-state"), tc=TimeContext("Asia/Shanghai"), me="群聊的 AI 方（按原文成员标签区分）" if view == "group" else view.upper(),
            user="用户", model_cmd=model_cmd, timeout=600, review=True, facts=p["facts"],
            min_messages=60, stale_minutes=90, max_chars=30000, notify_cmd=None, notify_after=3)
        result = ba.flush(cfg) if kind == "flush" else ba.run_once(cfg)
        ledger = ba.Ledger(cfg.state_dir, cfg.source)
        result["cursor_epoch"] = ledger.data["cursor_epoch"]
        result["cursor_keys"] = ledger.data["cursor_keys"]
        return result
    if kind == "backfill":
        from passive_facts import BACKFILL_RULES
        receipts = []
        for _ in range(200):
            text = call("latent_fact_backfill", {"action": "next", "limit": 8})
            marker = "\n["
            offset = text.find(marker)
            if offset < 0:
                result = call("latent_fact_backfill", {"action": "finish"})
                return {"status": "done", "receipts": receipts, "finish": result}
            batch = json.loads(text[offset + 1:])
            reply = generate(BACKFILL_RULES + "\n只输出 JSON 对象 {\"items\":[{\"block\":...,\"facts\":[...]}]}。\n" + json.dumps(batch, ensure_ascii=False), p["agent"])
            parsed = json.loads(ba.clean_reply(reply))
            receipts.append(call("latent_fact_backfill", {"action": "submit", "items": parsed["items"]}))
        return {"status": "failed", "error": "已达本次回填批次上限，保留进度，可继续运行"}
    if kind == "initialize":
        step = data.get("step", "inspect")
        if step not in {"inspect", "extract", "choose-sections", "preview", "questionnaire", "answers", "confirm", "route", "ship"}:
            raise ValueError("step")
        out = directory / "initialization"
        out.mkdir(exist_ok=True)
        previous_state = out / "init_state.json"
        if previous_state.is_file():
            history = out / ".lune-init-history"
            history.mkdir(exist_ok=True)
            shutil.copyfile(previous_state, history / (uuid.uuid4().hex + ".json"))
        argv = [str(source / "src/memory_init.py"), "--out", str(out), "--client", "generic", "--timezone", "Asia/Shanghai", "--step", step]
        corpus = directory / "memory"
        if corpus.is_dir():
            argv += ["--corpus", str(corpus)]
        if "persona" in data:
            (directory / "persona-input.md").write_text(str(data["persona"]), encoding="utf-8")
        persona = directory / "persona-input.md"
        if persona.exists():
            argv += ["--persona", str(persona)]
        if step in {"questionnaire", "preview", "choose-sections"}:
            argv += ["--json"]
        if step == "confirm" and "decisions" not in data:
            argv += ["--list", "--json"]
        choices = {"use_original_as_is", "treat_current_as_original", "continue_legacy"}
        if data.get("existing_persona_choice") in choices:
            argv += ["--existing-persona-choice", data["existing_persona_choice"]]
        if step == "route":
            route = data.get("route", "local")
            if route not in {"zero-dep", "local", "cloud"}:
                raise ValueError("route")
            argv += ["--route", route]
        fields = {"candidates": "--candidates", "answers": "--answers-json",
            "decisions": "--decisions-json", "section_decisions": "--section-decisions-json",
            "original_section_decisions": "--original-section-decisions-json"}
        for key, flag in fields.items():
            if key in data:
                file = out / (key + ".json")
                file.write_text(json.dumps(data[key], ensure_ascii=False), encoding="utf-8")
                argv += [flag, str(file)]
        if data.get("accept_persona_drift") is True:
            argv += ["--accept-persona-drift"]
        if step == "ship":
            argv += ["--backup-corpus"]
        # Run the original CLI entry point, keeping its actual errors and guards.
        sys.argv = argv
        capture = UTF8Capture()
        from contextlib import redirect_stdout
        with locked(root), redirect_stdout(capture):
            try:
                runpy.run_path(str(source / "src/memory_init.py"), run_name="__main__")
                code = 0
            except SystemExit as exc:
                code = exc.code or 0
            if code == 0 and step == "ship":
                result = out / "persona.md"
                if not result.is_file():
                    raise RuntimeError("原版没有生成人格成品，未激活预览文件")
                temp = directory / ".persona-active"
                temp.write_bytes(result.read_bytes())
                temp.replace(directory / "persona.md")
                (out / ".lune-shipped").write_text("verified native ship", encoding="utf-8")
        return {"status": "done" if code == 0 else "failed", "step": step, "output": capture.getvalue(), "exit_code": code}
    if kind == "import":
        from memory_import import load_any
        from memory_init import write_corpus
        name = Path(str(data.get("name", "history.json"))).name
        if Path(name).suffix.lower() not in {".json", ".txt", ".md", ".markdown"}:
            raise ValueError("文件格式不支持")
        import hashlib
        content = str(data.get("content", ""))
        digest = hashlib.sha256(content.encode()).hexdigest()
        destination = directory / "memory" / "imports" / digest
        with locked(root):
            if destination.exists():
                return {"status": "done", "duplicate": True}
            with tempfile.TemporaryDirectory(dir=directory) as tmp:
                file = Path(tmp) / name
                file.write_text(content, encoding="utf-8")
                entries = load_any(file)
                if not entries:
                    raise ValueError("没有可导入的对话")
                stage = Path(tmp) / "memory"
                files, _ = write_corpus(stage, entries)
                destination.parent.mkdir(parents=True, exist_ok=True)
                stage.rename(destination)
        return {"status": "done", "entries": len(entries), "files": len(files)}
    if kind == "backup":
        destination = root / (view + "-backup.zip")
        temp = root / (".backup-" + uuid.uuid4().hex)
        with locked(root), zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(directory.rglob("*")):
                if file.is_file() and not file.is_symlink():
                    archive.write(file, str(file.relative_to(directory)))
        os.chmod(temp, 0o600)
        temp.replace(destination)
        return {"status": "done", "download": "/lune/native/" + view + "/backup"}
    raise ValueError("kind")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--model"]:
        print(generate(sys.stdin.read(), sys.argv[2]))
    else:
        source = Path(sys.argv[1]).resolve()
        sys.path.insert(0, str(source / "src"))
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            print(json.dumps(run(json.load(sys.stdin), source), ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({"status": "failed", "error": str(exc)[:1500]}, ensure_ascii=False))
            sys.exit(1)
