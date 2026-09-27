"""
Audio for a hearing recording, as 16 kHz mono MP3 chunks the transcription model accepts.

    get_audio(video_id="...", proxy=None) -> Path            # YouTube, via yt-dlp (audio only)
    get_audio(senate_url="https://www.senate.gov/isvp/?comm=epw&filename=epw120623") -> Path
    get_audio(local="hearing.mp4") -> Path
    chunks(path, minutes=25, overlap=5) -> [(chunk_path, offset_seconds), ...]

Recordings that aren't on YouTube (the Senate player, local files) are cut into 25-minute
chunks and uploaded; a chunk the model can't return whole is cut again. ffmpeg does the
extraction and cutting.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from congress_api.senate.isvp import archive_url, live_url, parse_player_url

FFMPEG_AUDIO = ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k"]


def get_audio(out_dir: Path, video_id: str = "", senate_url: str = "", local: str = "", proxy: str | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    if video_id:
        out = out_dir / f"{video_id}.mp3"
        if not out.exists():
            import yt_dlp
            with tempfile.TemporaryDirectory() as tmp:
                opts = {"format": "bestaudio/best", "outtmpl": f"{tmp}/%(id)s.%(ext)s", "quiet": True, "no_warnings": True, "logger": logging.getLogger("yt_dlp")}
                if proxy:
                    opts.update(proxy=proxy, nocheckcertificate=True)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
                src = next(Path(tmp).glob(f"{video_id}.*"))
                run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), *FFMPEG_AUDIO, str(out)])
        return out
    if senate_url:
        comm, fn = parse_player_url(senate_url) or (None, None)
        if not comm:
            raise ValueError(f"not a senate.gov player URL: {senate_url}")
        out = out_dir / f"{fn}.mp3"
        if not out.exists():
            for url in (live_url(comm, fn), archive_url(comm, fn)):
                if run(["ffmpeg", "-loglevel", "error", "-y", "-i", url, *FFMPEG_AUDIO, str(out)], check=False) == 0 and out.exists():
                    break
            else:
                raise RuntimeError(f"no stream answered for {fn}")
        return out
    if local:
        out = out_dir / (Path(local).stem + ".mp3")
        if not out.exists():
            run(["ffmpeg", "-loglevel", "error", "-y", "-i", local, *FFMPEG_AUDIO, str(out)])
        return out
    raise ValueError("give a video_id, senate_url or local file")


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


def cut(path: Path, start: float, length: float) -> Path:
    """A piece of an audio file, [start, start+length) seconds."""
    piece = path.with_name(f"{path.stem}.{int(start):06d}-{int(start + length):06d}.mp3")
    if not piece.exists():
        run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(path), "-c", "copy", str(piece)])
    return piece


def chunks(path: Path, minutes: float = 25, overlap: float = 0) -> list[tuple[Path, float]]:
    """Cut into chunks of `minutes` (plus `overlap` seconds shared with the next one). Returns (path, offset_seconds)."""
    total = duration(path)
    step = minutes * 60
    out, start, n = [], 0.0, 0
    while start < total:
        length = min(step + overlap, total - start)
        piece = path.with_name(f"{path.stem}.part{n:02d}.mp3")
        if not piece.exists():
            run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(path), "-c", "copy", str(piece)])
        out.append((piece, start))
        start += step
        n += 1
    return out


def run(cmd: list[str], check: bool = True) -> int:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr[-400:]}")
    return r.returncode
