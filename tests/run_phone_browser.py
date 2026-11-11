"""Headless UI smoke for the independent Émoi small-phone mode.

This is an anonymous local HTTP server with no model accounts or tokens.
Exercise iOS-size and desktop-size screens, local-only contact drafts,
app navigation, wallpaper UI and dual-mode persistence.
"""
from __future__ import annotations
import http.server
import os
from pathlib import Path
import socketserver
import tempfile
import threading
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

WEB=Path(__file__).resolve().parents[1]/"web"
OUT=Path(os.environ.get("EMOI_SCREENSHOT_DIR",tempfile.mkdtemp(prefix="emoi-phone-screens-")))
OUT.mkdir(parents=True,exist_ok=True)

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True

def wait(driver,predicate):
    return WebDriverWait(driver,18).until(predicate)

def main():
    os.chdir(WEB)
    with Server(("127.0.0.1",0),Handler) as http:
        threading.Thread(target=http.serve_forever,daemon=True).start()
        options=Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=390,844")
        options.add_argument("--user-data-dir="+tempfile.mkdtemp(prefix="emoi-phone-browser-"))
        driver=webdriver.Chrome(options=options)
        try:
            url=f"http://127.0.0.1:{http.server_address[1]}/"
            driver.set_window_size(390,844);driver.get(url)
            wait(driver,lambda d:d.execute_script("return !!window.EmoiUiMode && !!window.EmoiApp"))
            wait(driver,lambda d:d.execute_script("return document.body.dataset.phoneScreen==='home'"))
            assert driver.execute_script("return document.body.dataset.uiMode")=="phone"
            assert driver.execute_script("return document.querySelectorAll('.ep-app').length")==8
            assert driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth+1"),"390px horizontal overflow"
            assert driver.find_element(By.ID,"emoiPhone").is_displayed()
            driver.save_screenshot(str(OUT/"phone-home-390.png"))
            # Crystal glass: all icons are SVG with low-opacity backdrop surfaces,
            # not solid coloured boxes or emoji glyphs.
            optical=driver.execute_script("""
              const a=[...document.querySelectorAll('.ep-app-icon')];
              return {
                n:a.length, svg:a.every(x=>!!x.querySelector('svg')),
                sample:getComputedStyle(a[0]).backgroundImage,
                dock:getComputedStyle(document.querySelector('.ep-dock')).backgroundImage,
                hero:getComputedStyle(document.querySelector('.ep-hero-widget')).backgroundImage,
                wallpaper:getComputedStyle(document.documentElement).getPropertyValue('--emoi-active-wallpaper')
              }
            """)
            assert optical["n"]==8 and optical["svg"]
            assert "rgba" in optical["sample"] and "rgba" in optical["dock"]
            assert "lily-water.webp" in optical["wallpaper"],optical
            # A wallpaper change must pass through the same translucent lenses.
            driver.execute_script("""document.documentElement.style.setProperty(
              '--emoi-active-wallpaper','url("assets/water-light.webp")')""")
            driver.save_screenshot(str(OUT/"phone-home-water-wallpaper-390.png"))
            driver.execute_script("window.EmoiWallpapers.activate('page:home')")
            # A real search button opens Contacts, not an empty decorative label.
            driver.find_element(By.CSS_SELECTOR,'.ep-home-search').click()
            assert driver.execute_script("return document.body.dataset.phoneScreen")=="contacts"
            driver.execute_script("window.EmoiUiMode.openHome()")

            # The phone UI starts with NO pre-made AI identities, regardless of the
            # legacy GPT/Claude room identifiers preserved inside the back end.
            driver.find_element(By.CSS_SELECTOR,'[data-ep-app="chat"]').click()
            wait(driver,lambda d:d.execute_script("return document.body.dataset.phoneScreen==='messages'"))
            assert "还没有联系人" in driver.find_element(By.ID,"emoiPhoneView").text
            driver.save_screenshot(str(OUT/"phone-messages-empty-390.png"))

            driver.find_element(By.CSS_SELECTOR,'.ep-list-actions .ep-round').click()
            dlg=driver.find_element(By.ID,"epContactDialog")
            assert dlg.get_attribute("open") is not None
            dlg.find_element(By.CSS_SELECTOR,'input[name="name"]').send_keys("测试联系人")
            dlg.find_element(By.CSS_SELECTOR,'textarea[name="notes"]').send_keys("仅本机人物档案")
            dlg.find_element(By.CSS_SELECTOR,'button[type="submit"]').click()
            wait(driver,lambda d:"测试联系人" in d.find_element(By.ID,"emoiPhoneView").text)
            driver.save_screenshot(str(OUT/"phone-contacts-390.png"))
            store=driver.execute_script("return JSON.parse(localStorage.getItem('emoi-ui-contacts-v1'))")
            assert len(store)==1 and store[0]["name"]=="测试联系人"
            driver.find_element(By.CSS_SELECTOR,'[data-entry="'+store[0]["id"]+'"]').click()
            assert "尚未绑定 AI 服务" in driver.find_element(By.ID,"emoiPhoneView").text
            driver.save_screenshot(str(OUT/"phone-contact-detail-390.png"))

            # iMessage-style screen is a real independent local conversation;
            # a send cannot silently fall back to the legacy GPT/Claude rooms.
            driver.execute_script("window.EmoiUiMode.openApp('chat')")
            driver.find_element(By.CSS_SELECTOR,'[data-entry="'+store[0]["id"]+'"]').click()
            wait(driver,lambda d:d.execute_script("return document.body.dataset.phoneScreen==='imessage'"))
            self_peer=driver.find_element(By.CSS_SELECTOR,'.ep-im-peer-info strong').text
            assert self_peer=="测试联系人"
            assert "未连接 AI" in driver.find_element(By.ID,"emoiPhoneView").text
            area=driver.find_element(By.CSS_SELECTOR,'.ep-im-composer textarea')
            area.send_keys("这条消息只属于测试联系人")
            driver.find_element(By.CSS_SELECTOR,'.ep-im-submit').click()
            wait(driver,lambda d:"这条消息只属于测试联系人" in d.find_element(By.CSS_SELECTOR,'.ep-im-history').text)
            assert "尚未发送给 AI" in driver.find_element(By.CSS_SELECTOR,'.ep-im-delivery').text
            stored=driver.execute_script("return JSON.parse(localStorage.getItem('emoi-ui-conversation-drafts-v1'))")
            assert len(stored['contact:'+store[0]['id']])==1
            driver.save_screenshot(str(OUT/"phone-imessage-real-390.png"))

            # A second contact sees a clean, distinct history.
            driver.execute_script("window.EmoiUiMode.openApp('contacts')")
            driver.find_element(By.CSS_SELECTOR,'.ep-action-primary').click()
            dlg=driver.find_element(By.ID,"epContactDialog")
            dlg.find_element(By.CSS_SELECTOR,'input[name="name"]').send_keys("第二位AI")
            dlg.find_element(By.CSS_SELECTOR,'button[type="submit"]').click()
            driver.execute_script("window.EmoiUiMode.openApp('chat')")
            new_id=driver.execute_script("return JSON.parse(localStorage.getItem('emoi-ui-contacts-v1'))[1].id")
            driver.find_element(By.CSS_SELECTOR,'[data-entry="'+new_id+'"]').click()
            assert "这条消息只属于测试联系人" not in driver.find_element(By.CSS_SELECTOR,'.ep-im-history').text
            assert not driver.find_elements(By.CSS_SELECTOR,'.ep-im-history .ep-im-row')

            # A user-created group is a transparent local draft, not a phantom
            # connected chat or shared memory store.
            driver.execute_script("window.EmoiUiMode.openApp('chat')")
            driver.execute_script("window.EmoiUiMode.openApp('chat')")
            driver.find_element(By.CSS_SELECTOR,'.ep-quiet-link').click()
            group=driver.find_element(By.ID,"epGroupDialog")
            group.find_element(By.CSS_SELECTOR,'input[name="name"]').send_keys("自定义小群")
            group.find_element(By.CSS_SELECTOR,'.ep-member input[type="checkbox"]').click()
            group.find_element(By.CSS_SELECTOR,'button[type="submit"]').click()
            wait(driver,lambda d:"自定义小群" in d.find_element(By.ID,"emoiPhoneView").text)
            assert "群聊草稿" in driver.find_element(By.ID,"emoiPhoneView").text
            assert len(driver.execute_script("return JSON.parse(localStorage.getItem('emoi-ui-groups-v1'))"))==1
            driver.save_screenshot(str(OUT/"phone-group-draft-390.png"))

            # Existing apps open their real implementations in the phone frame.
            driver.execute_script("window.EmoiUiMode.openHome()")
            driver.find_element(By.CSS_SELECTOR,'[data-ep-app="memory"]').click()
            wait(driver,lambda d:d.execute_script("return document.querySelector('#workspaceDialog').open"))
            assert driver.execute_script("return document.querySelector('#workspaceDialog').dataset.page")=="memory"
            driver.save_screenshot(str(OUT/"phone-memory-app-390.png"))
            driver.execute_script("document.querySelector('#workspaceDialog').close()")

            # Mode switching must never clear contact data or alter relay auth.
            driver.execute_script("window.EmoiUiMode.setMode('art')")
            assert driver.execute_script("return document.body.dataset.uiMode")=="art"
            assert driver.find_element(By.ID,"app").is_displayed()
            driver.save_screenshot(str(OUT/"artistic-existing-390.png"))
            driver.execute_script("window.EmoiUiMode.setMode('phone')")
            assert driver.execute_script("return document.body.dataset.phoneScreen")=="home"
            assert driver.execute_script("return JSON.parse(localStorage.getItem('emoi-ui-contacts-v1')).length")==2

            driver.set_window_size(1440,900);driver.refresh()
            wait(driver,lambda d:d.execute_script("return !!window.EmoiUiMode && document.body.dataset.phoneScreen==='home'"))
            width=driver.execute_script("return Math.round(document.querySelector('#emoiPhone').getBoundingClientRect().width)")
            assert 395<=width<=415,f"Expected centered phone on desktop, got {width}"
            frame=driver.execute_script("return document.querySelector('#emoiPhone').getBoundingClientRect().toJSON()")
            assert abs((frame['left']+frame['right'])/2 - 720)<3
            assert driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth+1")
            driver.save_screenshot(str(OUT/"phone-desktop-1440.png"))

            # Settings allow both independent visual modes.
            driver.find_element(By.CSS_SELECTOR,'.ep-home-top-actions button[aria-label="界面设置"]').click()
            assert "小手机" in driver.find_element(By.ID,"emoiPhoneView").text
            assert "艺术模式" in driver.find_element(By.ID,"emoiPhoneView").text
            driver.save_screenshot(str(OUT/"phone-settings-1440.png"))
        finally:
            driver.quit();http.shutdown()
    print("Émoi phone UI browser smoke passed; captured:",OUT)

if __name__=="__main__":
    main()
