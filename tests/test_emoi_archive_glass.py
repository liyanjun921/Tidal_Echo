"""Static integration checks for Émoi's shared shell and per-page wallpapers.

These verify wiring and packaging, not real iOS Safari rendering.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


class ArchiveGlassTests(unittest.TestCase):
    def test_page_and_chat_wallpaper_triggers_exist(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="chatWallpaperButton"', html)
        self.assertIn('id="pageWallpaperButton"', html)
        self.assertIn('src="emoi-wallpapers.js"', html)
        self.assertIn('href="emoi-archive-glass.css"', html)
        self.assertLess(html.index('src="emoi-wallpapers.js"'), html.index('src="app.js"'))

    def test_js_hooks_follow_current_page_and_room(self):
        js = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("window.EmoiWallpapers?.activate('chat:'+id)", js)
        self.assertIn("window.EmoiWallpapers?.activate('page:'+name)", js)
        code = (WEB / "emoi-wallpapers.js").read_text(encoding="utf-8")
        for required in ["wallpaper-page:", "localStorage", "indexedDB", "lastChat",
                         "workspace.addEventListener('close'", "MAX_BYTES",
                         "blob instanceof Blob", "URL.revokeObjectURL"]:
            self.assertIn(required, code)
        self.assertNotIn("fetch(", code)
        self.assertNotIn("XMLHttpRequest", code)

    def test_service_worker_includes_art_and_js(self):
        sw = (WEB / "sw.js").read_text(encoding="utf-8")
        for name in ("emoi-wallpapers.js", "emoi-archive-glass.css",
                     "emoi-archive-botanical.svg", "emoi-archive-nocturne.svg"):
            self.assertIn(name, sw)
        for name in ("emoi-archive-botanical.svg", "emoi-archive-nocturne.svg"):
            self.assertTrue((WEB / "assets" / name).is_file())

    def test_accessibility_and_reduced_motion(self):
        css = (WEB / "emoi-archive-glass.css").read_text(encoding="utf-8")
        self.assertIn('prefers-reduced-motion:reduce', css)
        self.assertIn('forced-colors:active', css)
        self.assertIn('aria-pressed', (WEB / "emoi-wallpapers.js").read_text(encoding="utf-8"))
        self.assertIn('dialog', (WEB / "emoi-wallpapers.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
