"""Missing tails and failed events cannot be certified by a fast completed prefix."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from analyze_scene_cases import summarize

class TimingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'scene-cases-test.json'
        self.trace=self.root/'native-presents.csv'
        (self.root/'session.json').write_text(json.dumps(dict(profile_kind='analysis',pid=5,process_start_ticks='123')))
        self.report=dict(measurement_schema=1,pid=5,process_start_ticks='123',session=str(self.root/'session.json'),
            trace=str(self.trace),status='completed',cases=[dict(id='authored',status='completed',steps=[
                dict(step=dict(op='load'),status='completed',frame_before=1,frame_after=2),
                dict(step=dict(op='event'),status='completed',frame_before=2,frame_after=5)])])
        self.write_trace([10000000,1000000000,10000000,10000000,10000000])
    def write_trace(self,intervals):
        stamp=0;rows=['frame,return_ns,interval_ns']
        for i,ns in enumerate(intervals,1):stamp+=ns;rows.append(f'{i},{stamp},{ns}')
        self.trace.write_text('\n'.join(rows)+'\n')
    def run_report(self):
        self.path.write_text(json.dumps(self.report));return summarize(self.path)
    def test_loading_is_separate_and_boundary_is_not_lost(self):
        r=self.run_report();load,event=r['operations']
        self.assertEqual(load['timing']['max_ms'],1000)
        self.assertEqual(event['timing']['frames'],3)
        self.assertEqual(event['timing']['first_frame'],3)
        self.assertTrue(r['all_event_call_intervals_within_budget'])
        self.assertFalse(r['performance_certified'])
    def test_slow_event_is_not_hidden_by_average(self):
        self.write_trace([10000000,10000000,10000000,50000000,10000000])
        r=self.run_report();self.assertFalse(r['all_event_call_intervals_within_budget'])
        self.assertEqual(r['operations'][1]['timing']['over_budget_frames'],1)
    def test_missing_tail_and_failed_case_leave_verdict_unknown(self):
        self.write_trace([10000000]*4)
        r=self.run_report();self.assertFalse(r['complete_trace_coverage'])
        self.assertIsNone(r['all_event_call_intervals_within_budget'])
        self.write_trace([10000000]*5);self.report['status']='failed'
        self.assertIsNone(self.run_report()['all_event_call_intervals_within_budget'])
    def test_identity_and_old_reports_rejected(self):
        self.report['pid']=6
        with self.assertRaises(ValueError):self.run_report()
        self.report['pid']=5;self.report.pop('measurement_schema')
        with self.assertRaises(ValueError):self.run_report()
    def test_no_frames_is_unavailable_and_wait_is_partial(self):
        e=self.report['cases'][0]['steps'][1];e['frame_after']=e['frame_before'];e['step']['op']='wait'
        r=self.run_report();self.assertFalse(r['operations'][1]['available'])
        self.assertTrue(r['operations'][1]['observed_suffix_only'])
        self.assertIsNone(r['all_event_call_intervals_within_budget'])

if __name__=='__main__':unittest.main()
