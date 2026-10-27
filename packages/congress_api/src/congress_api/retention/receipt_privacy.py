"""Public receipt fields: legacy cleanup patterns and new-writer URL/header rules."""
from bisect import bisect_right
from collections import Counter
from pathlib import PurePosixPath, PureWindowsPath
import re

# These named filesystem roots are the proposed B0 pattern, subject to the
# owner's review of the full scan. URL spans are excluded before matching.
LOCAL_PATH = re.compile(r'(?<![\w:/])(?:/(?:Users|home|private|tmp|var|opt|mnt|Volumes)/[^\s\'"<>;,\)\]]+|[A-Za-z]:\\[^\s\'"<>;,\)\]]+)')
URL = re.compile(r'https?://[^\s\'"<>]+', re.I)


def sensitive_header(name):
    return isinstance(name, str) and (name.lower() == 'authorization' or name.lower().endswith('cookie'))


def basename(value):
    return str(PureWindowsPath(value).name if re.match(r'^[A-Za-z]:\\', value)
               else PurePosixPath(value).name)


def cut_paths(value):
    """Return a string with local paths reduced, leaving every URL span intact."""
    spans = [(m.start(), m.end()) for m in URL.finditer(value)]
    starts = [start for start, _ in spans]
    matches = []
    for match in LOCAL_PATH.finditer(value):
        previous = bisect_right(starts, match.start()) - 1
        if previous < 0 or match.start() >= spans[previous][1]:
            matches.append(match)
    if not matches:
        return value, 0
    if len(matches) == 1 and matches[0].start() == 0 and not spans:
        return basename(value), 1  # A complete path can contain spaces.
    parts, last = [], 0
    for match in matches:
        parts.extend((value[last:match.start()], basename(match[0])))
        last = match.end()
    parts.append(value[last:])
    return ''.join(parts), len(matches)


def pointer_keys(line):
    """Protect only actual keys traversed by a capture pointer, in O(pointer length)."""
    protected = set()
    root_path = ('record',) if isinstance(line, dict) and 'record' in line else ()
    root = line.get('record') if root_path else line
    for capture in line.get('captures', []) if isinstance(line, dict) else []:
        node, path = root, root_path
        for part in capture.get('pointer', []):
            if isinstance(node, dict):
                protected.add((*path, part))
            try:
                node = node[part]
            except (KeyError, IndexError, TypeError):
                break  # Validation separately reports unresolved historical pointers.
            path = (*path, part)
    return protected


def clean_older_line(line):
    """Apply only B0's two edits; return counts by kind, JSON path and safe example."""
    cuts, protected = Counter(), pointer_keys(line)

    def finding(kind, path, count=1, example='<removed>'):
        label = '.'.join('[]' if isinstance(p, int) else
                         '<local-key>' if cut_paths(str(p))[1] else str(p) for p in path)
        cuts[kind, label, example] += count

    def text(value, path, kind='path'):
        cleaned, count = cut_paths(value)
        if count:
            finding(kind, path, count, '<local>/' + basename(cleaned))
        return cleaned

    def walk(value, path):
        if isinstance(value, str):
            return text(value, path)
        if isinstance(value, list):
            if len(value) == 2 and sensitive_header(value[0]) and value[1] is not None:
                finding('header', (*path, 1))
                return [value[0], None]
            return [walk(child, (*path, i)) for i, child in enumerate(value)]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, child in value.items():
            location = (*path, key)
            if sensitive_header(key):
                if location in protected:
                    raise ValueError('Sensitive header is traversed by a pointer')
                finding('header', location)
                continue
            if key == 'value' and sensitive_header(value.get('name')):
                finding('header', location)
                continue
            new_key = key
            if cut_paths(key)[1]:
                if location in protected:
                    finding('protected_path', location)
                else:
                    new_key = text(key, location)
            if new_key in result:
                raise ValueError('Local path basename collision')
            # A pointer is an identifier, not a local filename value.
            result[new_key] = child if key == 'pointer' else walk(child, location)
        return result

    return walk(line, ()), cuts

