"""Late-created workers and exited/reused TIDs must replace the sampler's old list."""
import argparse
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--cc", default="cc")
args = parser.parse_args()

root = Path(__file__).resolve().parents[1]
source = (root/'host/posix/prof.c').read_text()
helper = source[source.index('static int sample_all_refresh('):source.index('static DWORD WINAPI sample_all_thread(')]
compiler = args.cc
if not compiler:
    raise SystemExit('SKIP: C compiler unavailable')
fixture = r'''
#include <stdio.h>
#include <string.h>
#include <assert.h>
typedef struct { int tid; char name[64]; int guest; } Task;
static Task current[6];
static int count;
static int tasks(Task *out, int capacity) {
 assert(capacity >= count); memcpy(out, current, count * sizeof(Task)); return count;
}
'''+helper+r'''
int main(void) {
 FILE *log=tmpfile(); assert(log);
 int ids[3]={0}; char names[3][64]={{0}};
 current[0]=(Task){1,"sampler",1};
 current[1]=(Task){2,"Main Thread",1};
 current[2]=(Task){3,"unrelated host",0};
 current[3]=(Task){4,"mkw_vk|worker",0}; count=4;
 assert(sample_all_refresh(log,1,ids,names,3)==2);
 assert(ids[0]==2 && ids[1]==4 && !strcmp(names[0],"Main_Thread"));
 assert(!strcmp(names[1],"mkw_vk_worker"));
 /* Main exited, a movie worker appeared, and TID4 is now unrelated. */
 current[1]=(Task){5,"MovieWorker",1}; current[3]=(Task){4,"unrelated replacement",0};
 assert(sample_all_refresh(log,1,ids,names,3)==1);
 assert(ids[0]==5 && !strcmp(names[0],"MovieWorker"));
 current[4]=(Task){6,"SecondMovieWorker",1}; count=5;
 assert(sample_all_refresh(log,1,ids,names,1)==1);
 rewind(log); char text[2048]={0}; fread(text,1,sizeof(text)-1,log);
 assert(strstr(text,"# thread 5 MovieWorker\n"));
 assert(strstr(text,"# thread_limit 1\n"));
 fclose(log);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    folder = Path(tmp)
    (folder/'test.c').write_text(fixture)
    binary = folder/('test.exe' if os.name == 'nt' else 'test')
    subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', str(folder/'test.c'), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('PASS: late workers, departed/reused TIDs, host filtering, sanitization and capacity reporting')
