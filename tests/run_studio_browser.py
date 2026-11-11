"""Headless Chrome viewport smoke + screenshots for the real Émoi Studio markup.

Runs against a temporary static server with NO account, no model, and no private data.
Artifacts are for human review; passing asserts does not imply artistic parity.
"""
from __future__ import annotations
import http.server
import os
from pathlib import Path
import shutil
import socketserver
import tempfile
import threading
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/"web"
OUTPUT=Path(os.environ.get("EMOI_SCREENSHOT_DIR", tempfile.mkdtemp(prefix="emoi-studio-")))
OUTPUT.mkdir(parents=True,exist_ok=True)

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args):
        pass

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True

def visible(driver, selector):
    return driver.execute_script("return !!document.querySelector(arguments[0]) && getComputedStyle(document.querySelector(arguments[0])).display !== 'none';",selector)

def check_mobile(driver,url):
    driver.set_window_size(390,844)
    driver.get(url)
    WebDriverWait(driver,18).until(lambda d:d.execute_script("return !!window.EmoiStudio && !!window.EmoiApp"))
    assert driver.execute_script("return document.body.dataset.emoiView")=="home"
    assert visible(driver,"#emoiHome")
    assert visible(driver,".emoi-home-grid")
    assert visible(driver,"#emoiBottomDock")
    count=driver.execute_script("return document.querySelectorAll('.emoi-home-tile').length")
    assert count==8, f"Expected 8 actual interactive home modules, got {count}"
    assert driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1"),"mobile overflow"
    driver.save_screenshot(str(OUTPUT/"studio-mobile-home-390.png"))
    driver.find_element(By.CSS_SELECTOR,'[data-emoi-chat="gpt"]').click()
    assert driver.execute_script("return document.body.dataset.emoiView")=="chat"
    assert visible(driver,"#chatArea")
    assert visible(driver,"#chatForm")
    assert not visible(driver,"#emoiBottomDock")
    driver.save_screenshot(str(OUTPUT/"studio-mobile-chat-390.png"))
    driver.execute_script("window.EmoiStudio.goHome()")
    driver.find_element(By.CSS_SELECTOR,'.emoi-home-tile[data-page="memory"]').click()
    WebDriverWait(driver,8).until(lambda d:d.execute_script("return document.querySelector('#workspaceDialog').open"))
    assert driver.execute_script("return document.querySelector('#workspaceDialog').dataset.page")=="memory"
    driver.save_screenshot(str(OUTPUT/"studio-mobile-memory-390.png"))
    driver.execute_script("document.querySelector('#workspaceDialog').close()")

def check_desktop(driver,url):
    driver.set_window_size(1440,920)
    driver.get(url)
    WebDriverWait(driver,18).until(lambda d:d.execute_script("return !!window.EmoiStudio && !!window.EmoiApp"))
    assert visible(driver,".emoi-studio-rail")
    assert visible(driver,".emoi-studio-threads")
    assert visible(driver,"#chatArea")
    columns=driver.execute_script("return getComputedStyle(document.querySelector('.emoi-studio')).gridTemplateColumns")
    assert len(columns.split())==3, f"Expected three real desktop columns: {columns}"
    assert driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1"),"desktop overflow"
    driver.save_screenshot(str(OUTPUT/"studio-desktop-chat-1440.png"))

def main():
    os.chdir(WEB)
    with Server(("127.0.0.1",0),Handler) as http:
        port=http.server_address[1]
        threading.Thread(target=http.serve_forever,daemon=True).start()
        options=Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--force-device-scale-factor=1")
        options.add_argument("--window-size=390,844")
        # Ensure each run starts with a pristine browser profile & zero prior tokens.
        options.add_argument("--user-data-dir="+tempfile.mkdtemp(prefix="emoi-studio-chrome-"))
        driver=webdriver.Chrome(options=options)
        try:
            url=f"http://127.0.0.1:{port}/"
            check_mobile(driver,url)
            check_desktop(driver,url)
        finally:
            driver.quit()
            http.shutdown()
    print(f"Émoi Studio mobile/desktop browser smoke passed; screenshots: {OUTPUT}")

if __name__=="__main__":
    main()
