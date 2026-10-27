"""Sample a directly owned child process without reading its environment."""
import subprocess


class ProcessResourceError(RuntimeError):
    """The host cannot measure the child reliably."""


def resident_bytes(pid):
    try:
        result = subprocess.run(['/bin/ps', '-o', 'rss=', '-p', str(pid)],
                                capture_output=True, text=True, timeout=1)
        if result.returncode not in (0, 1) or result.stderr.strip():
            raise ProcessResourceError('Process memory measurement unavailable')
        return int(result.stdout.strip()) * 1024 if result.stdout.strip() else 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ProcessResourceError('Process memory measurement unavailable') from exc
