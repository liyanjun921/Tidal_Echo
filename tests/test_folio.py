"""Persistent merged state, Chinese matching and UI namespace boundaries."""
import os
from pathlib import Path
import tempfile
import unittest
from backend.ombre_folio import State,SCORING,topic_score,ui_text
from backend.lune_ombre import themed_html


class FolioTests(unittest.TestCase):
    def test_state_survives_restart_and_stays_in_its_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'gpt';b=Path(tmp)/'claude';a.mkdir();b.mkdir()
            one=State(a);one.write('id',{'summary':'private GPT marker'},'extra')
            self.assertEqual(State(a).extra('id')['summary'],'private GPT marker')
            self.assertEqual(State(b).extra('id'),{})
            self.assertEqual(one.path.stat().st_mode&0o777,0o600)
            with self.assertRaises(ValueError):one.read('id',table='invalid')

    def test_chinese_strict_matching_uses_real_words_and_summary(self):
        cfg={**SCORING,'strict_keyword_mode':True}
        hit={'content':'我们后来散步回家。','metadata':{'name':'海边','summary':'蓝色风筝','tags':[],'domain':['日常']}}
        miss={'content':'学习法律。','metadata':{'name':'教室','tags':[],'domain':['学习']}}
        self.assertGreater(topic_score('蓝色风筝',hit,cfg),topic_score('蓝色风筝',miss,cfg))
        self.assertEqual(topic_score('蓝色风筝',miss,cfg),0)

    def test_namespace_rewrite_preserves_external_and_native_ui(self):
        raw='<script>fetch("/api/buckets");const API="/api";new Worker("/v2/worker.js");fetch("https://other.example/api/buckets")</script>'
        merged=ui_text(raw)
        self.assertEqual(ui_text(merged),merged)
        output=themed_html('<html><head></head>'+merged+'</html>','gpt')
        self.assertIn('/ombre/gpt/api/folio/buckets',output)
        self.assertIn('API="/ombre/gpt/api/folio"',output)
        self.assertIn('/ombre/gpt/v2/worker.js',output)
        self.assertIn('https://other.example/api/buckets',output)

    def test_optional_scoring_stays_bounded_and_title_bonus_is_effective(self):
        memory={'content':'','metadata':{'name':'风筝','domain':[],'tags':[],'valence':.8}}
        a=topic_score('风筝',memory,SCORING)
        b=topic_score('风筝',memory,{**SCORING,'title_hit_bonus':25})
        self.assertGreater(b,a)
        self.assertLessEqual(b,1)


if __name__=='__main__':unittest.main()
