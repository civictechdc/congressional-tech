"""Read cue text without confusing cue identifiers or metadata with speech."""
import html
import re


def cue_lines(vtt: str) -> list[list[str]]:
    if not re.match(r'\A\ufeff?WEBVTT(?:[ \t\r\n]|$)', vtt):
        raise ValueError('Caption response is not WebVTT')
    # A cue payload can contain a line made of spaces (YouTube uses one as
    # an empty display row). Only an actually empty line ends the cue.
    blocks = re.split(r'\n{2,}', vtt.replace('\r\n', '\n').replace('\r', '\n'))
    if '-->' in blocks[0]:
        raise ValueError('WebVTT header is not separated from its cues')
    result = []
    for block in blocks[1:]:
        lines = block.strip().splitlines()
        if not lines or re.match(r'^(?:NOTE|STYLE|REGION)(?:\s|$)', lines[0]):
            continue
        timing = next((i for i, line in enumerate(lines[:2]) if '-->' in line), None)
        if timing is None:
            raise ValueError('WebVTT block has no cue timing')
        text = [html.unescape(re.sub(r'<[^>]+>', '', line)).strip() for line in lines[timing + 1:]]
        if any(text):
            result.append([line for line in text if line])
    return result
