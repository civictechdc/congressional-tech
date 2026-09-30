"""Interpret HLS subtitle declarations and timed WebVTT cues."""

import re

from congress_shared.webvtt import cue_lines

from congress_api.models.media import HLSRendition, WebVTTCue


class IncompleteCaptionsError(RuntimeError):
    """A declared caption playlist or segment could not be completely read."""


def _require_playlist(body: str, url: str) -> None:
    lines = body.lstrip("\ufeff \t\r\n").splitlines()
    if not lines or lines[0].strip() != "#EXTM3U":
        raise IncompleteCaptionsError(f"Missing or invalid HLS playlist: {url}")


def _subtitle_uri(master: str) -> str | None:
    """Playlist URI for subtitles: prefer English, then DEFAULT=YES, else the first track."""
    tracks = []
    for line in master.splitlines():
        if line.strip().startswith("#EXT-X-MEDIA:"):
            attrs = HLSRendition.model_validate(dict((name, value.strip('"')) for name, value in re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', line)))
            if attrs.type == "SUBTITLES":
                if not attrs.uri:
                    raise IncompleteCaptionsError("Declared subtitle track has no playlist URI")
                tracks.append(attrs)
    if not tracks:
        return None
    for track in tracks:
        if (track.language or "").lower().startswith("eng"):
            return track.uri
    for track in tracks:
        if (track.default or "").upper() == "YES":
            return track.uri
    return tracks[0].uri


def parsed_cues(body: str, url: str = "retained WebVTT") -> list[WebVTTCue]:
    """Typed cue extraction; retained source text still includes all metadata."""
    if not re.match(r"\A\ufeff?WEBVTT(?:[ \t\r\n]|$)", body):
        raise IncompleteCaptionsError(f"Missing or invalid WebVTT segment: {url}")
    # Whitespace-only payload lines are valid; only empty lines separate cues.
    blocks = re.split(r"\n{2,}", body.replace("\r\n", "\n").replace("\r", "\n"))
    if "-->" in blocks[0]:
        raise IncompleteCaptionsError(f"WebVTT header is not separated from its cues: {url}")
    result = []
    for block in blocks[1:]:
        lines = block.strip("\n").splitlines()
        if not lines or re.match(r"^(?:NOTE|STYLE|REGION)(?:\s|$)", lines[0]):
            continue
        timing = lines[0] if "-->" in lines[0] else lines[1] if len(lines) > 1 else ""
        match = re.fullmatch(r"((?:\d{2,}:)?[0-5]\d:[0-5]\d\.\d{3})[ \t]+-->[ \t]+((?:\d{2,}:)?[0-5]\d:[0-5]\d\.\d{3})(?:[ \t]+.*)?", timing)
        if not match:
            raise IncompleteCaptionsError(f"Invalid WebVTT cue timing: {url}")
        try:
            after = timing.split("-->", 1)[1].strip().split(maxsplit=1)
            result.append(WebVTTCue(start=match[1], end=match[2], text=lines[1 if timing == lines[0] else 2:],
                                   identifier=None if timing == lines[0] else lines[0], settings=after[1] if len(after) > 1 else ""))
        except ValueError as error:
            raise IncompleteCaptionsError(f"WebVTT cue ends before it starts: {url}") from error
    return result


def cues(vtt: str) -> list[list[str]]:
    """Each cue's text lines, retaining numeric speech and excluding cue IDs."""
    parsed_cues(vtt)
    return cue_lines(vtt)


def merge_rollup(cue_lines: list[list[str]]) -> str:
    """Senate captions roll up: a cue shows the lines on screen, and the newest line grows word by
    word across cues while the older one stays. So a line that extends one of the last few lines
    replaces it, and a shorter copy of one of them is dropped; anything else is a new line."""
    lines: list[str] = []
    for cue in cue_lines:
        for line in cue:
            for j in range(len(lines) - 1, max(-1, len(lines) - 5), -1):
                if line.startswith(lines[j]):
                    lines[j] = line  # the line grew
                    break
                if lines[j].startswith(line):
                    break  # an older, shorter copy
            else:
                lines.append(line)
    return "\n".join(lines) + "\n"
