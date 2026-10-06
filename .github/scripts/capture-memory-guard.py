"""Run capture with the same sampled 12 GiB process-memory stop used locally."""
import argparse
import json
from pathlib import Path
import signal
import subprocess
import time


def process_rss(pid):
    rows = [tuple(map(int, line.split())) for line in subprocess.check_output(
        ['ps', '-axo', 'pid=,ppid=,rss='], text=True).splitlines() if line.strip()]
    children = {pid}
    while True:
        found = {child for child, parent, _ in rows if parent in children}
        if found <= children:
            break
        children.update(found)
    return sum(rss * 1024 for child, _, rss in rows if child in children)


def run(command, output, *, limit_bytes=12 * 1024**3, interval=5, sample=process_rss):
    peak = 0
    stopped = False
    started = time.monotonic()
    child = subprocess.Popen(command)
    try:
        while child.poll() is None:
            current = sample(child.pid)
            peak = max(peak, current)
            if current > limit_bytes and not stopped:
                print(f'Capture memory stop: {current} bytes exceeds {limit_bytes}', flush=True)
                child.send_signal(signal.SIGTERM)
                stopped = True
            try:
                child.wait(timeout=interval)
            except subprocess.TimeoutExpired:
                pass
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGTERM)
            child.wait()
        result = dict(peak_process_rss_bytes=peak, stop_threshold_bytes=limit_bytes,
                      stopped_for_memory=stopped, elapsed_seconds=time.monotonic() - started,
                      child_exit_code=child.returncode)
        output.write_text(json.dumps(result, indent=2) + '\n')
    return child.returncode or (1 if stopped else 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('a capture command is required')
    raise SystemExit(run(command, args.output))


if __name__ == '__main__':
    main()
