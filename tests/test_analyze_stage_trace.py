"""Nested work must remain separate; exclude boundary-crossing totals."""
import importlib.util,tempfile
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'scripts/analyze_stage_trace.py'
spec=importlib.util.spec_from_file_location('stage',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as d:
 p=Path(d)
 (p/'frames.csv').write_text('frame,return_ns,interval_ns\n1,10000000,10000000\n2,30000000,20000000\n')
 (p/'trace.csv').write_text('operation,submission,thread,stage,start_ns,end_ns,wall_ns,cpu_ns\n'
 'outer,1,1,take_inclusive,12000000,28000000,16000000,2000000\n'
 'inner,1,1,wait,14000000,26000000,12000000,1000000\n'
 'other,0,2,cross,5000000,15000000,10000000,-1\n')
 r=m.analyze(p/'trace.csv',p/'frames.csv',2,2)
 assert len(r['stages'])==2 and r['complete_stage_rows']==2
 assert r['boundary_crossing_rows_excluded_from_totals']==1
 assert r['slow_intervals'][0]['interval_ms']==20
 assert len(r['slow_intervals'][0]['overlapping_stages_not_additive'])==3
 assert r['stages'][0]['wall_minus_cpu_ns']==11000000
print('PASS: nested stages, unknown CPU time and clipped frame windows')
