"""Direction, boundedness, replay, provenance and read/write separation."""
from copy import deepcopy
import asyncio
import json
import math
import random
import time
import unittest
from unittest.mock import AsyncMock,patch

from backend import desire_kernel as k,lune_desire as d,lune_wren as w
import tests.test_wren as _wren_tests


class KernelTests(unittest.TestCase):
    def setUp(self):
        self.base={key:.2 for key in k.REGISTRY}
        self.state=k.new_state(0,self.base)
        self.cfg=k.config()

    def test_circadian_bounds_peak_trough_pressure_and_period(self):
        cfg=k.config({'circadian':{'enabled':True}})
        for key,phase in cfg['circadian']['phases'].items():
            for offset in range(48):
                _,meta=k.circadian(self.base,offset/2,cfg)
                self.assertLessEqual(abs(meta['offsets'][key]),.08*phase['amp']+1e-12)
                self.assertEqual(meta['offsets']['stress'],0)
            _,peak=k.circadian(self.base,phase['peak'],cfg)
            _,trough=k.circadian(self.base,phase['peak']+12,cfg)
            self.assertAlmostEqual(peak['offsets'][key],.08*phase['amp'])
            self.assertAlmostEqual(trough['offsets'][key],-.08*phase['amp'])
        self.assertEqual(self.base,{key:.2 for key in k.REGISTRY})
        a,_=k.circadian(self.base,0,cfg);b,_=k.circadian(self.base,24,cfg)
        for key in a:self.assertAlmostEqual(a[key],b[key])

    def test_clock_disabled_exact_identity_and_no_input_mutation(self):
        source=deepcopy(self.base)
        out,_=k.circadian(self.base,7,self.cfg)
        self.assertEqual(out,source)
        self.assertEqual(self.base,source)
        out['stress']=1
        self.assertEqual(self.base,source)

    def test_overnight_missing_recent_old_window_compatible(self):
        now=100000
        self.assertEqual(k.overnight(now,None,self.cfg),0)
        self.assertEqual(k.overnight(now,now-2*3600,self.cfg),0)
        self.assertEqual(k.overnight(now,now-15*3600,self.cfg),0)
        self.assertGreater(k.overnight(now,now-8.5*3600,self.cfg),0)
        self.assertLessEqual(k.overnight(now,now-3*3600,self.cfg),.6)

    def test_morning_once_per_day_is_base_pulse_not_clock_feedback(self):
        cfg=k.config({'morning':{'enabled':True},'circadian':{'enabled':True}})
        state=k.new_state(0)
        one,_=k.advance(state,3600,self.base,cfg,hour=7,day='2026-10-25')
        two,_=k.advance(one,3600,self.base,cfg,hour=7,day='2026-10-25')
        self.assertEqual(one['drive'],two['drive'])
        self.assertGreater(one['drive']['libido'],one['drive']['curiosity'])
        self.assertEqual(state['morning_day'],'')

    def test_pulses_diminish_discount_and_dedupe(self):
        cfg=k.config({'message_pulses':True})
        one,first=k.message(self.state,'帮我看看代码报错',1,1,cfg)
        duplicate,_=k.message(one,'帮我看看代码报错',1,2,cfg)
        self.assertEqual(one,duplicate)
        two,second=k.message(one,'帮我看看代码报错',2,3,cfg)
        delta1=sum(c['delta'] for c in first if c['drive']=='curiosity')
        delta2=sum(c['delta'] for c in second if c['drive']=='curiosity')
        self.assertGreater(delta1,delta2)
        self.assertLess(two['drive']['curiosity'],1)

    def test_negative_and_relation_signals_do_not_guess_emotion_or_past(self):
        cfg=k.config({'message_pulses':True})
        for text in ['我！去！看！看！','之前我们分手吧那件事','假如我的隐私泄露了']:
            state,_=k.message(self.state,text,1,1,cfg)
            for key in ['stress','jealousy','protection','separation']:
                self.assertEqual(state['drive'][key],self.state['drive'][key])
        state,_=k.message(self.state,'我的隐私泄露了',1,1,cfg)
        self.assertGreater(state['drive']['protection'],.2)

    def test_self_drive_redline_user_pulse_never_weaker_and_attention_returns(self):
        state=k.new_state(0,{'curiosity':.95,'craft':.9,'attachment':.1})
        off,_=k.message(state,'回来了',1,1,k.config({'message_pulses':True}))
        cfg=k.config({'message_pulses':True,'self_drive':True})
        on,_=k.message(state,'回来了',1,1,cfg)
        self.assertGreaterEqual(on['drive']['attachment'],off['drive']['attachment'])
        self.assertEqual(k.choose(on,on['drive'],[],2,cfg)['intent'],'reach_out')

    def test_baseline_floor_clamped_and_interaction_pulls_back(self):
        cfg=k.config({'baseline_drift':True,'message_pulses':True})
        state=self.state
        for i in range(200):state,_=k.advance(state,(i+1)*86400,self.base,cfg)
        self.assertLessEqual(state['floor'],.5)
        before=state['floor']
        state,_=k.message(state,'回来了',1,state['at'],cfg)
        self.assertAlmostEqual(state['floor'],before*.4)

    def test_coupled_random_initial_states_200_ticks_bounded_deterministic(self):
        cfg=k.config({'coupling':True,'noise':True,'self_drive':True,'habits':True})
        rng=random.Random(13)
        state=k.new_state(0,{key:rng.random() for key in k.REGISTRY})
        clone=deepcopy(state)
        for i in range(200):
            state,_=k.advance(state,(i+1)*300,self.base,cfg,seed='same')
            clone,_=k.advance(clone,(i+1)*300,self.base,cfg,seed='same')
            self.assertEqual(state,clone)
            self.assertTrue(all(math.isfinite(v) and 0<=v<=1 for v in state['drive'].values()))
        self.assertGreater(len(set(round(x,5) for x in state['drive'].values())),3)

    def test_action_requires_evidence_refractory_habit_and_self_material(self):
        cfg=k.config({'habits':True,'self_drive':True})
        unchanged,changes=k.satisfy(self.state,'explore',10,cfg,verified=False,material=True)
        self.assertEqual(unchanged,self.state);self.assertEqual(changes,[])
        done,_=k.satisfy(self.state,'explore',10,cfg,verified=True,material=True)
        self.assertAlmostEqual(done['habit']['curiosity'],.006)
        self.assertEqual(done['self_actions'],1)
        self.assertGreater(done['cooldown']['curiosity'],int(10//300))
        decision=k.choose(done,{**done['drive'],'curiosity':1},[],10,cfg)
        self.assertNotEqual(decision.get('drive'),'curiosity')
        for i in range(50):done,_=k.satisfy(done,'explore',10,cfg,verified=True)
        self.assertLessEqual(done['habit']['curiosity'],.12)

    def test_fatigue_gate_and_adaptive_interval_respects_hard_bounds(self):
        display={**self.base,'fatigue':.8,'curiosity':1}
        self.assertEqual(k.choose(self.state,display,[],0,self.cfg)['intent'],'rest')
        for values in [{key:0 for key in k.REGISTRY},{key:1 for key in k.REGISTRY},display]:
            value=k.interval(values,7200,3600,14400)
            self.assertTrue(3600<=value<=14400)
            self.assertGreaterEqual(k.interval(values,7200,3600,14400,quiet=True),7200)

    def test_topic_match_uses_overlap_not_exact_sentence(self):
        a=k.topic_keys('海边小书的封面计划')
        b=k.topic_keys('继续海边小书封面方案')
        self.assertTrue(k.same_topic(a,b))
        self.assertFalse(k.same_topic(a,k.topic_keys('午餐吃番茄鸡蛋面')))

    def test_positive_local_classifier_confidence_and_margin(self):
        vectors=[[1,0,0,0],[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
        self.assertEqual(d.positive_class(vectors)[0],'curiosity')
        vectors[2]=[1,0,0,0]
        self.assertIsNone(d.positive_class(vectors)[0])


class DesireHostTests(unittest.TestCase):
    setUp= _wren_tests.WrenTests.setUp
    message= _wren_tests.WrenTests.message
    tool= _wren_tests.WrenTests.tool
    status= _wren_tests.WrenTests.status
    setting= _wren_tests.WrenTests.setting
    stopped= _wren_tests.WrenTests.stopped

    def enable(self,**flags):
        response=self.setting(desire=k.config(flags))
        self.assertEqual(response.status_code,200,response.text)

    def thought(self,visibility='shared'):
        return self.tool(action='thought',source_id=self.mid,quote='海边那本小书',drive='reflection',visibility=visibility).json()['id']

    def test_reads_do_not_write_base_and_clock_off_identity(self):
        self.enable(circadian={'enabled':True})
        with w.connection(self.path) as db:before=db.execute('SELECT value FROM lune_wren_drives WHERE scope=\'gpt\'').fetchone()[0]
        one=self.status();two=self.status()
        with w.connection(self.path) as db:after=db.execute('SELECT value FROM lune_wren_drives WHERE scope=\'gpt\'').fetchone()[0]
        self.assertEqual(before,after)
        self.assertNotEqual(one['body']['drive_display'],one['body']['drive'])
        self.enable(circadian={'enabled':False})
        body=self.status()['body'];self.assertEqual(body['drive'],body['drive_display'])

    def test_topic_variants_promote_with_all_evidence_retained(self):
        for text in ['海边小书的封面计划','继续海边小书封面方案','海边小书封面再看看']:
            source=self.message(text)
            with w.connection(self.path) as db:
                w.record_thought(db,'gpt',{'source_id':source,'quote':text,'drive':'craft','visibility':'shared'},time.time())
        thoughts=self.status()['thoughts']
        self.assertEqual(len(thoughts),1)
        self.assertEqual(thoughts[0]['state'],'fixation')
        with w.connection(self.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM lune_wren_thought_sources').fetchone()[0],3)

    def test_experience_provenance_snapshot_private_and_bounded_consumption(self):
        tid=self.thought()
        self.enable(experiences=True)
        value={'action':'experience','source_memory_id':tid,'content':'我记得这本小书带来的认真。','valence':.6,'arousal':.5,'tension':.2,'response_tendency':'engage','growth_delta':'growth','priority':85,'visibility':'shared'}
        self.assertEqual(self.tool(**{**value,'source_memory_id':'foreign'}).status_code,422)
        for i in range(7):self.assertEqual(self.tool(**{**value,'content':value['content']+str(i)}).status_code,200)
        self.tool(**{**value,'content':'PRIVATE_E_HIDDEN','visibility':'typo'})
        self.assertNotIn('PRIVATE_E_HIDDEN',json.dumps(self.status(),ensure_ascii=False))
        with w.connection(self.path) as db:
            cfg=w.config(db,'gpt');d.step(db,'gpt',cfg,time.time(),force=True)
            self.assertEqual(db.execute('SELECT count(*) FROM lune_desire_experiences WHERE consumed=1').fetchone()[0],5)
            self.assertEqual(len(json.loads(db.execute('SELECT body FROM lune_desire_experiences LIMIT 1').fetchone()[0])['drive_snapshot']),15)
        self.assertNotIn(value['content'],w.context(self.path,'lune-gpt','gpt'))

    def test_satisfaction_host_success_only_and_duplicate_proof(self):
        self.enable(enabled=True,habits=True,self_drive=True)
        tid=self.thought()
        self.assertEqual(self.tool(action='satisfy',id=tid).status_code,409)
        d.record_tool(self.path,'lune-gpt','gpt','run','latent_search',{},'ERROR: failed')
        self.assertEqual(self.tool(action='satisfy',id=tid).status_code,409)
        result=json.dumps({'matches':[{'content':'真实检索材料'*30}]},ensure_ascii=False)
        d.record_tool(self.path,'lune-gpt','gpt','run','latent_search',{},result)
        d.record_tool(self.path,'lune-gpt','gpt','run','latent_search',{},result)
        self.assertEqual(len(self.status()['body']['actions']),1)
        self.assertEqual(self.tool(action='satisfy',id=tid).status_code,200)
        self.assertEqual(self.status()['body']['self_drive']['actions'],1)

    def test_bad_nested_settings_rejected_and_flags_default_off(self):
        body=self.status()['body']
        self.assertTrue(all(not body['flags'][key] for key in k.FLAGS))
        self.assertEqual(self.tool(action='thought',source_id=self.mid,quote='海边那本小书',drive='jealousy',visibility='shared').status_code,422)
        for raw in [{'circadian':[]},{'circadian':{'phases':'bad'}},{'morning':{'max_hours':2,'min_hours':4}},{'noise':'true'}]:
            self.assertEqual(self.setting(desire=raw).status_code,422)

    def test_optional_local_classifier_once_real_message_only_no_negative_guess(self):
        self.enable(message_pulses=True,semantic_pulses=True)
        with w.connection(self.path) as db:w.advance_body(db,'gpt',w.config(db,'gpt'),time.time())
        vectors=[[1,0,0,0],[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
        with patch('backend.lune_memory.LatentEngine.worker',new=AsyncMock(return_value={'vectors':vectors})) as embed:
            for _ in range(2):asyncio.run(d.classify_message(self.path,'lune-gpt','gpt','想继续做海边那本小书。',self.mid))
            self.assertEqual(embed.await_count,1)
            self.assertEqual(self.status()['body']['local_classifier'][0]['status'],'matched')
        with patch.dict('os.environ',{'DESIRE_COUPLING':'1'}):self.assertTrue(d.boot_defaults()['coupling'])


if __name__=='__main__':unittest.main()
