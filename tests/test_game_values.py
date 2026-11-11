"""Scalar bindings and delayed engine writes, without game assets."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import game_values

RUN_ALL_SKIP = {'windows': 'Linux runtime API and Unix session isolation'}


class GameValuesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.run=Path(self.tmp.name); self.info=dict(profile_kind='analysis')
        self.layout=dict(slots_pointer_offset=0,slot_count_offset=8,values_pointer_offset=16,
                         value_count_offset=24,value_stride=8,value_offset=4)
        self.profile=dict(manager_pointer=8, scalar_tables={'bool':self.layout,'int':self.layout},
                          values={'count':dict(type='int',key=17),'flag':dict(type='bool',key=17)},
                          dispatch=dict(scalar_calls={'configured':True}))
        (self.run/'scene-bindings.json').write_text(json.dumps(self.profile))
        self.data=bytearray(2048)
        for offset,value,fmt in [(8,128,'Q'),(128,256,'Q'),(136,4,'I'),(144,512,'Q'),(152,2,'I'),
                                 (264,17,'I'),(268,1,'I'),(524,3,'i')]:
            struct.pack_into('<'+fmt,self.data,offset,value)
        self.now=0.;self.sequence=0;self.polls=0;self.pending=None;self.ignore=False;self.mode='exclusive';self.allowed=True;self.phase='dispatched'
        for attr,fn in [('monotonic',lambda:self.now),('sleep',self.sleep)]:
            p=patch.object(game_values.time,attr,fn);p.start();self.addCleanup(p.stop)
    def sleep(self,seconds):self.now+=seconds
    def read_memory(self,address,size):return dict(data_hex=self.data[address:address+size].hex())
    def scene_state(self,path):return {}
    def event_state(self):return dict(ready=True,active=False)
    def request(self,command):
        if command=='status':return dict(control=self.mode,buttons=0,sticks=[0]*4,last_present_age_ms=0,
                                          presents=int(self.now*60),input_sequence=0,applied_sequence=0)
        if command=='guest info':
            self.polls+=1
            if self.polls==3 and self.pending is not None and not self.ignore:struct.pack_into('<i',self.data,524,self.pending)
            return dict(sequence=self.sequence,phase=self.phase,allowed=self.allowed)
        if command.startswith('guest cancel'):return dict(canceled=False)
        self.pending=int(command.split()[-1]);self.sequence+=1
        return dict(sequence=self.sequence)
    def test_read_signed_int_and_bool(self):
        self.assertEqual(game_values.read_value(self,self.profile,'count'),3)
        struct.pack_into('<i',self.data,524,-7)
        self.assertEqual(game_values.read_value(self,self.profile,'count'),-7)
        self.assertTrue(game_values.read_value(self,self.profile,'flag'))
    def test_write_waits_for_readback(self):
        result=game_values.write_value(self,'count',-42)
        self.assertTrue(result['readback_verified']);self.assertGreaterEqual(self.polls,3)
        self.assertEqual(result['before'],3);self.assertEqual(result['observed'],-42)
    def test_dispatched_without_write_times_out(self):
        self.ignore=True
        with self.assertRaises(TimeoutError):game_values.write_value(self,'count',6,timeout=1)
        self.assertFalse(json.loads(next(self.run.glob('value-write-*')).read_text())['readback_verified'])
    def test_invalid_type_and_protected_profile(self):
        for name,value in [('count',True),('count',2**31),('flag',1),('missing',1)]:
            with self.assertRaises(ValueError):game_values.write_value(self,name,value)
        self.info['profile_kind']='player'
        with self.assertRaises(ValueError):game_values.write_value(self,'count',2)
        self.assertEqual(self.sequence,0)
    def test_unready_or_busy_worker_does_not_submit(self):
        for allowed,phase,message in [(False,'idle','has not polled'),
                                      (True,'pending','pending or executing'),
                                      (True,'executing','pending or executing')]:
            with self.subTest(allowed=allowed,phase=phase):
                self.allowed,self.phase=allowed,phase
                with self.assertRaisesRegex(RuntimeError,message):
                    game_values.write_value(self,'count',7)
                self.assertEqual(self.sequence,0)
                self.assertIsNone(self.pending)
        reports=[json.loads(p.read_text()) for p in self.run.glob('value-write-*')]
        self.assertEqual(len(reports),3)
        self.assertTrue(all(r['status']=='failed' and 'dispatch_before' in r for r in reports))

    def test_missing_and_out_of_bounds_records(self):
        struct.pack_into('<I',self.data,268,2)
        with self.assertRaisesRegex(RuntimeError,'outside'):game_values.read_value(self,self.profile,'count')
        struct.pack_into('<I',self.data,264,0)
        with self.assertRaisesRegex(RuntimeError,'not found'):game_values.read_value(self,self.profile,'count')


if __name__=='__main__':unittest.main()
