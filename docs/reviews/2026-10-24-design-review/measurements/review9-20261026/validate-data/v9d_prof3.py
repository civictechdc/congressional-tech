import sys, os, cProfile, pstats
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v9d_paths_lib as m
cProfile.run("m.scan(m.R+'/youtube/api/2026-09-29/assemble-20260930.jsonl.gz')",'prof.out'); pstats.Stats('prof.out').sort_stats('tottime').print_stats(6)
