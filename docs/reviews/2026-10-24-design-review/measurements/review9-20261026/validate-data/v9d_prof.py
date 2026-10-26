import sys, time, os, cProfile, pstats
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v9d_paths_lib as m
R=m.R
files=sorted(os.path.join(d,f) for d,_,fs in os.walk(R) for f in fs if f.endswith('.gz'))
big=sorted(files,key=os.path.getsize)[-1]
for fp in [files[0], files[500], files[1500]]:
    t=time.time(); m.scan(fp); print(round(time.time()-t,2), os.path.getsize(fp)//1e6, fp[len(R):][:50])
cProfile.run('m.scan(files[1500])','prof.out'); pstats.Stats('prof.out').sort_stats('cumtime').print_stats(8)
