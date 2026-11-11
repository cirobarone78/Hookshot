"""Keep nested and concurrent wall coverage separate and retain exact CPU evidence."""
import importlib.util
import tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('timeline',root/'scripts/export_renderer_timeline.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
assert m.union_ns([(0,10),(2,8),(8,12),(15,17)])==14
assert m.union_ns([])==0
with tempfile.TemporaryDirectory() as d:
 p=Path(d)
 f=p/'frames.csv';s=p/'stages.csv'
 f.write_text('frame,return_ns,interval_ns\n1,100,100\n2,200,100\n')
 s.write_text('operation,submission,thread,stage,start_ns,end_ns,wall_ns,cpu_ns\n'
              'outer,1,9007199254740999,work,25,175,150,100\n'
              'inner,1,9007199254740999,work,50,150,100,90\n'
              'other,2,88,wait,75,125,50,-1\n')
 result=m.export(s,f,2,2)
 frame=result['metadata']['frames'][0]
 assert frame['instrumented_wall_ns_per_thread_not_additive']=={'9007199254740999':75,'88':25}
 spans=[e for e in result['traceEvents'] if e['ph']=='X' and e['cat']!='native_present']
 assert spans[0]['dur']==.075 and spans[0]['args']['whole_thread_cpu_ns']==100
 assert spans[0]['args']['clipped'] and spans[2]['args']['whole_thread_cpu_ns'] is None
 assert all(isinstance(e['tid'],int) and e['tid']<3 for e in spans)
 assert result['metadata']['origin_monotonic_ns']==100
 assert result['metadata']['trace_row_limit']==1000000
 limited=s.read_text().splitlines()
 s.write_text(limited[0]+',trace_row_limit\n'+'\n'.join(r+',3' for r in limited[1:])+'\n')
 assert m.export(s,f)['metadata']['trace_row_limit_reached']
 try:m.export(s,f,3,4)
 except ValueError:pass
 else:raise AssertionError('Missing frame range accepted')
 s.write_text(s.read_text().replace('25,175,150','25,175,151'))
 try:m.export(s,f)
 except ValueError:pass
 else:raise AssertionError('Malformed interval accepted')
print('PASS: nested/concurrent coverage, clipped CPU evidence, stable thread IDs and invalid data')
