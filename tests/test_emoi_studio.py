"""Visual-structure integration contract for the Émoi Studio UI.
These tests do not claim screenshot parity with the artistic design reference.
"""
import re
import unittest
from pathlib import Path
from html.parser import HTMLParser

WEB=Path(__file__).resolve().parents[1] / "web"

class Landmarks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids=[]
        self.buttons=[]
        self.tags=[]
    def handle_starttag(self, tag, attrs):
        attributes=dict(attrs)
        self.tags.append(tag)
        if "id" in attributes:
            self.ids.append(attributes["id"])
        if tag=="button":
            self.buttons.append(attributes)

class StudioStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(WEB/"index.html").read_text("utf-8")
        cls.css=(WEB/"emoi-studio.css").read_text("utf-8")
        cls.js=(WEB/"emoi-studio.js").read_text("utf-8")
        cls.landmarks=Landmarks()
        cls.landmarks.feed(cls.html)

    def test_single_ids_and_existing_live_controls_preserved(self):
        ids=self.landmarks.ids
        self.assertEqual(len(ids),len(set(ids)),"Duplicate DOM id")
        for item in ("app","chatArea","chatStream","messageInput","chatForm",
                     "roomButton","composerPlus","micButton","workspaceDialog",
                     "emoiHome","emoiBottomDock","emoiStudio","homeWallpaperButton"):
            self.assertIn(item,ids)
        self.assertEqual(self.html.count('<main '),1)
        self.assertEqual(self.html.count('</main>'),1)

    def test_real_page_and_room_navigation_not_inert_decorations(self):
        self.assertIn('data-emoi-chat="gpt"',self.html)
        for item in ("memory","reading","cinema","journal","calendar","todo","appearance"):
            self.assertIn('data-page="'+item+'"',self.html)
        for item in ("gpt","claude","group"):
            self.assertIn('data-room="'+item+'"',self.html)
        self.assertIn("window.EmoiApp?.openChat",self.js)
        self.assertIn("window.EmoiWallpapers?.activate('page:home')",self.js)
        self.assertIn("workspaceDialog",self.js)

    def test_glass_presentation_and_mobile_breakpoints(self):
        for item in ("backdrop-filter:blur","grid-template-columns:190px",
                     "emoi-home-hero","emoi-bottom-dock","message-bubble",
                     "@media(max-width:1023px)"):
            self.assertIn(item,self.css)
        self.assertIn('prefers-reduced-motion:reduce',self.css)
        self.assertIn('assets/emoi-archive-botanical.svg',self.css)

    def test_no_fake_model_or_memory_content(self):
        self.assertNotIn("已连接",self.js)
        self.assertNotIn("setInterval(",self.js)
        self.assertNotIn("fetch(",self.js)
        self.assertNotIn("openai.com",self.js)

    def test_pwa_files_are_precached(self):
        sw=(WEB/"sw.js").read_text("utf-8")
        for item in ("emoi-studio.css","emoi-studio.js"):
            self.assertIn(item,sw)
            self.assertIn(item,self.html)
        self.assertIn('emoi-v6-studio-reference-layout',sw)

if __name__=="__main__":
    unittest.main()
