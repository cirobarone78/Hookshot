"""Scene playlists stop on failure and validate recipes before touching the game."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scene_cases import run_cases


class SceneCaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.run=Path(self.tmp.name); self.session=self.run/'session.json'; self.frame=100; self.info=dict(profile_kind='analysis'); self.calls=[]; self.fail=False
        (self.run/'scene-bindings.json').write_text(json.dumps(dict(image_sha256='authored')))
        self.plan=dict(schema=1,image_sha256='authored',cases=[dict(id='one',steps=[
            dict(op='load',scene='map',entrance='door'),dict(op='event',scene='map',event='intro'),
            dict(op='write',name='flag',value=True),dict(op='expect',name='flag',value=True)]),
            dict(id='two',steps=[dict(op='load',scene='next',entrance='door')])])
    def request(self,command):
        self.frame+=1; return dict(presents=self.frame)
    def scene_state(self,*args):return dict(fields=dict(current_scene='map'))
    def scene_load(self,*args):self.calls.append(('load',*args));return dict(status='completed')
    def event_play(self,*args):
        self.calls.append(('event',*args))
        if self.fail:raise TimeoutError('stuck')
        return dict(status='completed',samples=[1])
    def value_write(self,*args):self.calls.append(('write',*args));return dict(status='completed')
    def value_read(self,name):return dict(value=True)
    def screenshot(self):return 'authored.png'
    def test_order_and_honest_proof(self):
        r=run_cases(self,self.plan)
        self.assertEqual([c[0] for c in self.calls],['load','event','write','load'])
        self.assertEqual(r['status'],'completed');self.assertFalse(r['gameplay_verified'])
        self.assertFalse(r['performance_certified'])
        self.assertEqual(r['measurement_schema'],1)
        entries=[e for c in r['cases'] for e in c['steps']]
        self.assertTrue(all(e['frame_after']>e['frame_before'] for e in entries))
        self.assertTrue(all(a['frame_after']<b['frame_before'] for a,b in zip(entries,entries[1:])))
    def test_failure_prevents_later_mutations(self):
        self.fail=True
        with self.assertRaises(TimeoutError):run_cases(self,self.plan)
        self.assertEqual(len(self.calls),2)
        r=json.loads(next(self.run.glob('scene-cases-*')).read_text())
        self.assertEqual(r['status'],'failed');self.assertEqual(len(r['cases']),1)
        failed=r['cases'][0]['steps'][-1]
        self.assertEqual(failed['status'],'failed')
        self.assertIn('frame_before',failed);self.assertIn('frame_after',failed)
    def test_running_step_is_persisted_before_call(self):
        observed=[]
        def inspect(*args):
            path=next(self.run.glob('scene-cases-*.json'))
            report=json.loads(path.read_text())
            case=report['cases'][-1];step=case['steps'][-1]
            self.assertEqual(report['status'],'running')
            self.assertEqual(case['status'],'running')
            self.assertEqual(step['status'],'running')
            self.assertIn('frame_before',step)
            self.assertNotIn('finished_at',step)
            self.assertFalse(list(self.run.glob('*.tmp')))
            observed.append(step['step']['op'])
            return dict(status='completed')
        self.scene_load=inspect;self.event_play=inspect;self.value_write=inspect
        run_cases(self,self.plan)
        self.assertEqual(observed,['load','event','write','load'])

    def test_checkpoints_replace_complete_reports(self):
        replace=Path.replace
        replacements=[]
        def observe(source,target):
            target=Path(target)
            self.assertTrue(str(source).endswith('.json.tmp'))
            json.loads(source.read_text())
            if target.exists():json.loads(target.read_text())
            replacements.append(target)
            return replace(source,target)
        with patch.object(Path,'replace',observe):run_cases(self,self.plan)
        self.assertGreater(len(replacements),len(self.calls))
        self.assertEqual(len(set(replacements)),1)

    def test_interruption_retains_active_step_and_case_times(self):
        def interrupt(*args):raise KeyboardInterrupt('interrupted')
        self.event_play=interrupt
        with self.assertRaises(KeyboardInterrupt):run_cases(self,self.plan)
        report=json.loads(next(self.run.glob('scene-cases-*.json')).read_text())
        case=report['cases'][0];step=case['steps'][-1]
        self.assertEqual(report['status'],'failed')
        self.assertEqual(case['status'],'failed')
        self.assertEqual(step['status'],'failed')
        self.assertGreaterEqual(case['finished_at'],step['finished_at'])
        self.assertGreaterEqual(report['finished_at'],case['finished_at'])
        self.assertFalse(list(self.run.glob('*.tmp')))

    def test_missing_counter_stops_before_mutation(self):
        self.request=lambda command:dict(presents=None)
        with self.assertRaisesRegex(RuntimeError,'counter'):run_cases(self,self.plan)
        self.assertFalse(self.calls)

    def test_bad_late_step_rejected_before_mutation(self):
        self.plan['cases'][1]['steps'][0]['op']='shell'
        with self.assertRaises(ValueError):run_cases(self,self.plan)
        self.assertFalse(self.calls)
    def test_long_event_timeout_forwarded_and_bad_values_rejected(self):
        self.plan['cases'][0]['steps'][1]['timeout']=600
        received=[]
        original=self.event_play
        def play(*args, **kwargs):
            received.append(kwargs);return original(*args)
        self.event_play=play
        run_cases(self,self.plan)
        self.assertEqual(received,[dict(timeout=600)])
        for invalid in (True, float('nan'), 601, 0):
            self.plan['cases'][0]['steps'][1]['timeout']=invalid
            self.calls=[]
            with self.assertRaises(ValueError):run_cases(self,self.plan)
            self.assertFalse(self.calls)

    def test_image_profile_and_selection(self):
        self.plan['image_sha256']='wrong'
        with self.assertRaises(ValueError):run_cases(self,self.plan)
        self.plan['image_sha256']='authored'
        with self.assertRaises(ValueError):run_cases(self,self.plan,['missing'])
        self.info['profile_kind']='player'
        with self.assertRaises(ValueError):run_cases(self,self.plan)
        self.assertFalse(self.calls)


if __name__=='__main__':unittest.main()
