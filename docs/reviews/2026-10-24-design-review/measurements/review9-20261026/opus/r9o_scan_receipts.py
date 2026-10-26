"""Field-agnostic scan of the receipt mirror (read-only).

For every line of every receipt, walk the whole JSON value and report, by
normalized JSON path, where cookie headers, credential query parameters and
local filesystem paths occur, including:
  * dict keys named like cookie headers,
  * header pairs stored as [name, value] lists or {name:..., value:...} dicts,
  * raw header text inside strings ("set-cookie:"),
  * credential parameters in any URL-looking string, any field,
  * local paths as values and as key names, and last-segment collisions that
    cutting key names to their last segment would create inside one object,
  * pointers that pass through a key that is a local path.
Output: one JSON summary on stdout.
"""
import gzip, json, os, re, sys, collections
from multiprocessing import Pool
from urllib.parse import urlsplit, parse_qsl

COOKIE_NAMES = {"set-cookie", "cookie", "authorization", "proxy-authorization", "set-cookie2"}
CRED_KEYS = {"api_key", "apikey", "token", "access_token", "authorization", "x-api-key", "auth", "password", "secret", "client_secret"}
LOCAL_ROOTS = ("/Users/", "/home/", "/private/", "/tmp/", "/var/folders/", "/Volumes/", "/root/", "/opt/", "/mnt/", "/runner/", "/github/")
WIN_PATH = re.compile(r"^[A-Za-z]:\\")
EMBED_PATH = re.compile(r"(?:/Users/|/home/runner/|/private/var/|/private/tmp/|/var/folders/|/tmp/[A-Za-z0-9_.-]+/|file://)")
HEX = re.compile(r"^[0-9a-f]{16,}$")


def norm_key(k):
    if not isinstance(k, str):
        return "<K>"
    if is_local_path(k):
        return "<PATHKEY>"
    if k.startswith(("http://", "https://")):
        return "<URLKEY>"
    if HEX.match(k):
        return "<HEXKEY>"
    if k.isdigit():
        return "<NUM>"
    if len(k) > 48:
        return "<LONGKEY>"
    return k


def is_local_path(s):
    return isinstance(s, str) and (s.startswith(LOCAL_ROOTS) or bool(WIN_PATH.match(s)) or s.startswith("file://") or s.startswith("~/"))


def last_segment(s):
    s = s.rstrip("/\\")
    return re.split(r"[/\\]", s)[-1]


class Acc:
    def __init__(self):
        self.c = collections.Counter()      # (category, path) -> occurrences
        self.lines = collections.Counter()  # category -> lines having it
        self.misc = collections.Counter()
        self.examples = {}

    def hit(self, cat, path, line_cats, example=None):
        self.c[(cat, path)] += 1
        line_cats.add(cat)
        if example is not None and (cat, path) not in self.examples:
            self.examples[(cat, path)] = example[:200]


def walk(v, path, acc, line_cats, pathkey_ptrs):
    if isinstance(v, dict):
        # header stored as {"name": ..., "value": ...}
        nm = v.get("name") if isinstance(v.get("name"), str) else None
        if nm and nm.lower() in COOKIE_NAMES and "value" in v:
            acc.hit("cookie:name-value-dict", path, line_cats)
        segs = collections.Counter()
        for k, x in v.items():
            if isinstance(k, str):
                kl = k.lower()
                if kl in COOKIE_NAMES:
                    acc.hit("cookie:key", path + "." + kl, line_cats)
                if is_local_path(k):
                    acc.hit("path:key-name", path + ".<PATHKEY>", line_cats, k)
                    segs[last_segment(k)] += 1
            walk(x, path + "." + norm_key(k), acc, line_cats, pathkey_ptrs)
        dup = sum(n - 1 for n in segs.values() if n > 1)
        if dup:
            acc.hit("path:key-name-collision-on-cut", path, line_cats)
            acc.misc["key_name_collisions_extra_entries"] += dup
    elif isinstance(v, list):
        if len(v) == 2 and isinstance(v[0], str) and v[0].lower() in COOKIE_NAMES:
            acc.hit("cookie:pair-list", path, line_cats)
        for x in v:
            walk(x, path + "[]", acc, line_cats, pathkey_ptrs)
    elif isinstance(v, str):
        if is_local_path(v):
            acc.hit("path:value-absolute", path, line_cats, v)
        elif EMBED_PATH.search(v):
            acc.hit("path:value-embedded", path, line_cats, v)
        lv = v.lower()
        if "set-cookie:" in lv or "\ncookie:" in lv:
            acc.hit("cookie:in-string", path, line_cats)
        if ("?" in v or "&" in v) and ("http" in lv[:12] or lv.startswith("//") or lv.startswith("/")):
            try:
                q = urlsplit(v).query
            except ValueError:
                q = ""
            if q:
                ks = {k.lower() for k, _ in parse_qsl(q, keep_blank_values=True)}
                for k in ks & CRED_KEYS:
                    acc.hit(f"cred:{k}", path, line_cats, v)
                if "key" in ks:
                    host = (urlsplit(v).hostname or "").lower()
                    acc.misc[f"bare-key-param-host:{host}"] += 1


def scan_file(p):
    acc = Acc()
    rel = p
    m = re.search(r"/(\d{4}-\d{2}-\d{2})/", p)
    date = m.group(1) if m else None
    nlines = 0
    maxlen = 0
    try:
        with gzip.open(p, "rb") as f:
            for raw in f:
                nlines += 1
                maxlen = max(maxlen, len(raw))
                try:
                    obj = json.loads(raw)
                except Exception:
                    acc.misc["unparseable_lines"] += 1
                    continue
                line_cats = set()
                walk(obj, "$", acc, line_cats, None)
                # pointers through path-like keys
                caps = obj.get("captures") if isinstance(obj, dict) else None
                if isinstance(caps, list):
                    for e in caps:
                        ptr = e.get("pointer") if isinstance(e, dict) else None
                        if isinstance(ptr, list) and any(is_local_path(x) for x in ptr if isinstance(x, str)):
                            acc.hit("path:pointer-through-path-key", "$.captures[].pointer", line_cats, json.dumps(ptr)[:200])
                for cat in line_cats:
                    acc.lines[cat] += 1
                    fam = cat.split(":")[0]
                    acc.lines["ANY-" + fam] += 0  # placeholder for key existence
                fams = {c.split(":")[0] for c in line_cats}
                for fam in fams:
                    acc.lines["ANY-" + fam] += 1
                    if date and "2026-10-03" <= date <= "2026-10-16":
                        acc.lines["ANY-" + fam + "-in-20261003-20261016"] += 1
                if date and "2026-10-03" <= date <= "2026-10-16":
                    acc.misc["lines-in-20261003-20261016"] += 1
    except Exception as e:  # report, never hide
        acc.misc["file_errors"] += 1
        acc.examples[("file_error", rel)] = repr(e)[:200]
    acc.misc["lines"] += nlines
    acc.misc["files"] += 1
    return dict(c=list(acc.c.items()), lines=dict(acc.lines), misc=dict(acc.misc),
                ex=[(list(k), v) for k, v in acc.examples.items()], maxlen=maxlen, path=p, nlines=nlines)


def main(root, out):
    files = []
    for dp, dn, fn in os.walk(root):
        for f in fn:
            if f.endswith(".jsonl.gz"):
                files.append(os.path.join(dp, f))
    files.sort(key=lambda p: -os.path.getsize(p))
    tot = collections.Counter(); lines = collections.Counter(); misc = collections.Counter(); ex = {}
    maxlen = (0, None)
    per_file_lines = {}
    with Pool(10) as pool:
        for r in pool.imap_unordered(scan_file, files, chunksize=1):
            for k, v in r["c"]:
                tot[tuple(k)] += v
            lines.update(r["lines"]); misc.update(r["misc"])
            for k, v in r["ex"]:
                ex.setdefault(tuple(k), v)
            if r["maxlen"] > maxlen[0]:
                maxlen = (r["maxlen"], r["path"])
            per_file_lines[os.path.relpath(r["path"], root)] = r["nlines"]
    res = {
        "occurrences": sorted(([k[0], k[1], v] for k, v in tot.items()), key=lambda x: (x[0], -x[2])),
        "lines_with": dict(sorted(lines.items())),
        "misc": dict(sorted(misc.items())),
        "examples": {f"{k[0]} | {k[1]}": v for k, v in sorted(ex.items())},
        "max_line": maxlen,
    }
    with open(out, "w") as f:
        json.dump(res, f, indent=1)
    with open(out.replace(".json", "-lines.json"), "w") as f:
        json.dump(per_file_lines, f)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
