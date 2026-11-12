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
        options.add_argument("--enable-unsafe-swiftshader")
        options.add_argument("--use-angle=swiftshader")
        options.add_argument("--window-size=390,844")
        options.add_argument("--user-data-dir="+tempfile.mkdtemp(prefix="emoi-phone-browser-"))
        driver=webdriver.Chrome(options=options)
        try:
            url=f"http://127.0.0.1:{http.server_address[1]}/"
            driver.set_window_size(390,844);driver.get(url)
            wait(driver,lambda d:d.execute_script("return !!window.EmoiUiMode && !!window.EmoiApp"))
            wait(driver,lambda d:d.execute_script("return document.body.dataset.phoneScreen==='home'"))
            assert driver.execute_script("return document.body.dataset.uiMode")=="phone"
            assert driver.execute_script("return document.querySelectorAll('.ep-app').length")==9
            assert driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth+1"),"390px horizontal overflow"
            assert driver.find_element(By.ID,"emoiPhone").is_displayed()
            assert not driver.find_elements(By.CSS_SELECTOR,'.ep-statusbar,.ep-home-indicator'),"Fake phone furniture must not exist"
            mobile_bounds=driver.execute_script("return document.querySelector('#emoiPhone').getBoundingClientRect().toJSON()")
            inner_width=driver.execute_script("return window.innerWidth")
            assert abs(mobile_bounds["left"])<=1 and abs(mobile_bounds["right"]-inner_width)<=2,mobile_bounds
            assert driver.execute_script("return getComputedStyle(document.querySelector('#emoiPhone')).borderTopWidth")=="0px"
            ready = "return document.querySelectorAll('[data-ep-optics]').length > 0 && document.querySelectorAll('[data-ep-optics-ready]').length === document.querySelectorAll('[data-ep-optics]').length"
            snapshot = "return document.querySelector('[data-widget=calendar] canvas')?.toDataURL()"
            wait(driver, lambda d: d.execute_script(ready))
            initial = driver.execute_script(snapshot)
            assert initial and initial.startswith("data:image/png")
            assert driver.execute_script("""
              return Array.from(document.querySelectorAll('.ep-optical-canvas')).every(canvas => {
                const ctx = canvas.getContext('2d');
                const center = ctx.getImageData(canvas.width >> 1, canvas.height >> 1, 1, 1).data[3];
                return center > 20 && center < 85 && ctx.getImageData(0, 0, 1, 1).data[3] === 0;
              });
            """), "Glass must transmit the wallpaper and clip its corners"
            ink_toggle = '.ep-home-ink-toggle'
            home_colors = """
              return [...new Set(Array.from(document.querySelectorAll(
                '.ep-app-label,.ep-app-icon svg,.ep-dock-icon svg,.ep-widget-copy,.ep-desktop-clock,.ep-home-search'
              ), node => getComputedStyle(node).color))];
            """
            assert driver.execute_script(home_colors) == ['rgb(255, 255, 255)']
            assert driver.execute_script("""
              const root = document.documentElement;
              const frame = document.querySelector('#emoiPhone').getBoundingClientRect();
              return root.hasAttribute('data-emoi-home') && getComputedStyle(root).backgroundImage !== 'none' &&
                Math.abs(frame.top) < 1 && Math.abs(frame.bottom - innerHeight) < 2;
            """)
            driver.find_element(By.CSS_SELECTOR, ink_toggle).click()
            assert driver.execute_script(home_colors) == ['rgb(17, 17, 17)']
            driver.refresh()
            wait(driver, lambda d: d.execute_script(ready))
            assert driver.execute_script(home_colors) == ['rgb(17, 17, 17)']
            driver.find_element(By.CSS_SELECTOR, ink_toggle).click()
            assert driver.execute_script(home_colors) == ['rgb(255, 255, 255)']
            driver.save_screenshot(str(OUT/"responsive-home-390.png"))
            driver.find_element(By.CSS_SELECTOR, '.ep-home-edit').click()
            driver.find_element(By.CSS_SELECTOR, '[data-widget=calendar]').click()
            driver.find_element(By.XPATH, "//button[.='放大']").click()
            assert driver.find_element(By.CSS_SELECTOR, '[data-widget=calendar][data-wide]')
            driver.find_element(By.XPATH, "//button[.='后移']").click()
            assert driver.find_element(By.CSS_SELECTOR, '.ep-home-grid > :first-child').get_attribute('data-home-id') == 'widget:reading'
            driver.find_element(By.XPATH, "//button[.='移除']").click()
            assert not driver.find_elements(By.CSS_SELECTOR, '[data-widget=calendar]')
            driver.find_element(By.XPATH, "//button[.='添加小组件']").click()
            driver.find_element(By.XPATH, "//dialog[@aria-label='添加小组件']//button[.='日历']").click()
            driver.find_element(By.CSS_SELECTOR, '.ep-home-edit').click()
            driver.refresh()
            wait(driver, lambda d: d.execute_script(ready))
            assert driver.find_element(By.CSS_SELECTOR, '[data-widget=calendar]:first-child')
            assert not driver.find_elements(By.CSS_SELECTOR, '[data-widget=calendar][data-wide]')
            picker = 'button[aria-label="更换桌面壁纸"]'
            driver.find_element(By.CSS_SELECTOR, picker).click()
            driver.find_element(By.XPATH, "//button[contains(.,'流动水光')]").click()
            wait(driver, lambda d: d.execute_script(ready) and d.execute_script(snapshot) != initial)
            driver.save_screenshot(str(OUT/"phone-home-water-wallpaper-390.png"))
            driver.find_element(By.CSS_SELECTOR, picker).click()
            driver.find_element(By.XPATH, "//button[contains(.,'空白画纸')]").click()
            wait(driver, lambda d: d.execute_script("""
              return document.body.dataset.emoiWall === 'paper' && !document.querySelector('[data-ep-optics-ready]');
            """))
            assert driver.execute_script(home_colors) == ['rgb(255, 255, 255)']
            driver.save_screenshot(str(OUT/"phone-home-paper-390.png"))
            driver.find_element(By.CSS_SELECTOR, picker).click()
            driver.find_element(By.CSS_SELECTOR, 'input[aria-label="上传当前页面壁纸"]').send_keys(
                os.environ.get("EMOI_TEST_WALLPAPER", str(WEB/"assets/lily-water.webp")))
            wait(driver, lambda d: d.execute_script(ready) and d.execute_script("return document.body.dataset.emoiWall") == "custom")
            driver.save_screenshot(str(OUT/"phone-home-custom-390.png"))
            driver.refresh()
            wait(driver, lambda d: d.execute_script(ready) and d.execute_script("return document.body.dataset.emoiWall") == "custom")
            driver.find_element(By.CSS_SELECTOR, picker).click()
            driver.find_element(By.XPATH, "//button[contains(.,'星轨夜色')]").click()
            wait(driver, lambda d: d.execute_script(ready))
            driver.save_screenshot(str(OUT/"phone-home-night-390.png"))
            driver.find_element(By.CSS_SELECTOR, 'button[aria-label="打开日历"]').click()
            wait(driver, lambda d: d.execute_script("return document.querySelector('#workspaceDialog').open"))
            driver.execute_script("document.querySelector('#workspaceDialog').close()")
            wait(driver, lambda d: d.execute_script("return document.body.dataset.emoiWall === 'nocturne'"))
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
            viewport=driver.execute_script("return window.innerWidth")
            assert abs(width-viewport)<=2,f"Desktop MUST be a full-width website, not a 407px phone: {width} vs {viewport}"
            frame=driver.execute_script("return document.querySelector('#emoiPhone').getBoundingClientRect().toJSON()")
            assert abs(frame['left'])<=1 and abs(frame['right']-viewport)<=2,frame
            assert driver.execute_script("return getComputedStyle(document.querySelector('#emoiPhone')).borderTopWidth")=="0px"
            columns=driver.execute_script("return getComputedStyle(document.querySelector('.ep-home-grid')).gridTemplateColumns")
            assert len(columns.split())==8,f"Expected fluid desktop app launcher columns, got {columns}"
            assert driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth+1")
            wait(driver, lambda d: d.execute_script(ready))
            driver.save_screenshot(str(OUT/"responsive-desktop-1440.png"))
            driver.set_window_size(820, 1180)
            wait(driver, lambda d: len(d.execute_script(
                "return getComputedStyle(document.querySelector('.ep-home-grid')).gridTemplateColumns").split()) == 6)
            driver.save_screenshot(str(OUT/"responsive-tablet-820.png"))

            # Settings allow both independent visual modes.
            driver.find_element(By.CSS_SELECTOR,'.ep-dock button[aria-label="设置"]').click()
            assert "小手机" in driver.find_element(By.ID,"emoiPhoneView").text
            assert "艺术模式" in driver.find_element(By.ID,"emoiPhoneView").text
            driver.save_screenshot(str(OUT/"phone-settings-1440.png"))
        finally:
            driver.quit();http.shutdown()
    print("Émoi phone UI browser smoke passed; captured:",OUT)

if __name__=="__main__":
    main()
