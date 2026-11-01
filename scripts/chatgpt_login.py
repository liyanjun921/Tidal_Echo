"""Run on your own computer to authorize ChatGPT plan usage, with no API key.

python chatgpt_login.py
The browser completes OpenAI's official consent flow. Never paste tokens in chat.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import webbrowser

helper_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(helper_dir if (helper_dir / "lune_auth.py").is_file() else helper_dir.parent / "examples"))
from lune_auth import PlanError, PlanStore, start_login


def main():
    parser = argparse.ArgumentParser(description="Luné ChatGPT 订阅连接助手")
    parser.add_argument("--store", type=Path, default=Path.home() / ".lune" / "chatgpt-plan.json")
    parser.add_argument("--account", help="重新授权的已保存账户编号；留空连接新账户")
    parser.add_argument("--export", type=Path, help="生成供自己服务器导入的私人连接文件")
    args = parser.parse_args()
    store = PlanStore(args.store)
    try:
        login = start_login(store, args.account)
        if not webbrowser.open(login["authorization_url"]):
            print("无法打开本机浏览器。请在有浏览器的电脑上运行连接助手；不要在手机或远程终端直接运行。")
            return 1
        print("已打开 OpenAI 官方登录页。请确认应用名称和使用套餐权限，完成后回到这里。")
        for _ in range(600):
            state = store.status().get("last_attempt", {})
            if state.get("state") != "pending":
                break
            time.sleep(1)
        state = store.status().get("last_attempt", {})
        if state.get("state") != "completed":
            print(state.get("message", "登录未完成，请重新运行"))
            return 1
        print("登录已保存到当前电脑的私人目录。")
        if args.export:
            with store.locked():
                data = store.read()
                row = data["accounts"][data["active"]]
            args.export.parent.mkdir(parents=True, exist_ok=True)
            PlanStore(args.export).write({"format": "lune-chatgpt-session-v1", "session": row})
            with store.locked():
                local = store.read()
                for key in ("access_token", "refresh_token", "id_token"):
                    local["accounts"][data["active"]][key] = ""
                store.write(local)
            print("已生成私人连接文件。仅导入你自己的 HTTPS Luné 服务器；勿发给聊天、代码仓库或他人。导入后由服务器负责续期，避免电脑和服务器同时使用同一份授权。")
        return 0
    except PlanError as error:
        print(error.message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
