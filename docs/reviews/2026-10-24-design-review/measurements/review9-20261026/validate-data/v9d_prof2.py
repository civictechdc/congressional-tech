import sys, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v9d_paths_lib as m
files=sorted((os.path.join(d,f) for d,_,fs in os.walk(m.R) for f in fs if f.endswith('.gz')),key=os.path.getsize)[-4:]
for fp in files:
    t=time.time(); o,_,_,_=m.scan(fp); print(round(time.time()-t,1), os.path.getsize(fp)//1e6, fp[len(m.R):][:60], sum(o.values()), flush=True)
