"""Sample resident memory for a process and its children.

Publication cost measurement and the viewer benchmark share this sampler.
Missing samples stay explicit at the call site.
"""
import subprocess


def resident_tree(pid):
    """Same process-tree RSS sampler for every arm; missing samples are explicit."""
    rows = subprocess.run(['ps', '-axo', 'pid=,ppid=,rss='], capture_output=True, text=True, check=True, timeout=5).stdout
    processes = {int(p): (int(parent), int(rss) * 1024) for p, parent, rss in (line.split() for line in rows.splitlines())}
    children = {pid}
    while True:
        found = {p for p, (parent, _) in processes.items() if parent in children}
        if found <= children:
            return sum(processes[p][1] for p in children if p in processes)
        children.update(found)
