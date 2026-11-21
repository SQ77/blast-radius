"""Select tests by per-line coverage of the pinned sqlglot commit (covmap.json),
built offline from a coverage run of sqlglot's own tests (see buildmap.py)."""

import json
import os
import re
import sys
from bisect import bisect_left, bisect_right
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import importcheck

DATA = Path(os.environ.get("DATA_DIR", "/data"))
HERE = Path(__file__).resolve().parent
MAX_WORKERS = 8
WORKER_COST = 2.0
FAMILY = ("sqlglot/dialects/", "sqlglot/parsers/", "sqlglot/generators/", "sqlglot/typing/")
ATTR = re.compile(r"^\s*([A-Z][A-Z0-9_]+)\s*(?::[^=]+)?=[^=]")
HEDGE_SECONDS = 0.5
ATTR_NAME = re.compile(r"[A-Z][A-Z0-9_]+$")
PROBE = {"comment", "fixture"}  # diagnostic: run every test for these kinds of patch
DOC_SUFFIXES = (".md", ".rst", ".txt")


def skippable_line(text):
    s = text.strip()
    return not s or s.startswith("#")


def parse_patch(text):
    """path -> list of (kind, old_line, content); 'r' removed line, 'a' pure insertion point."""
    out, cur, hunk = {}, None, False
    old = 0
    prev_removed = False
    for line in text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(\S+) b/(\S+)", line)
            cur = m.group(1) if m else None
            if cur:
                out.setdefault(cur, [])
            hunk = False
        elif line.startswith("@@") and cur:
            m = re.match(r"@@ -(\d+)", line)
            old = int(m.group(1))
            hunk = True
            prev_removed = False
        elif cur and hunk and line[:1] == "-":
            out[cur].append(("r", old, line[1:]))
            old += 1
            prev_removed = True
        elif cur and hunk and line[:1] == "+":
            if not prev_removed:
                out[cur].append(("a", old, line[1:]))
        elif cur and hunk and line[:1] == " ":
            old += 1
            prev_removed = False
    return out


def main():
    tests = json.loads((DATA / "tests.json").read_text())["tests"]
    by_number = {t["number"]: t for t in tests}
    num_by_id = {t["id"]: t["number"] for t in tests}
    cov = json.loads((HERE / "covmap.json").read_text())
    remap = [num_by_id.get(i) for i in cov["ids"]]
    sets = [int(h, 16) for h in cov["sets"]]
    files = cov["files"]
    all_tests = {t["number"] for t in tests}
    file_tests = {}
    for t in tests:
        file_tests.setdefault(t["file"], set()).add(t["number"])

    def to_numbers(mask):
        res, i = set(), 0
        while mask:
            if mask & 1 and remap[i] is not None:
                res.add(remap[i])
            mask >>= 1
            i += 1
        return res

    class F:
        def __init__(self, d):
            self.l = d["l"]
            self.s = d["s"]
            self.imp = set(d["i"])
            self.st = d["st"]
            self.sc = d["sc"]
            self.line_mask = dict(zip(self.l, self.s))
            self._all = None
            self.family_mask = 0

        def range_mask(self, a, b):
            m = 0
            for k in range(bisect_left(self.l, a), bisect_right(self.l, b)):
                m |= sets[self.s[k]]
            return m

        def start_imp(self, ln):
            return True

        def family_mask_all(self, path):
            m = 0
            if path.startswith(FAMILY):
                stem = Path(path).stem
                for st_ in [stem] + cov.get("deps", {}).get(stem, []):
                    for d in FAMILY:
                        g = get(d + st_ + ".py")
                        if g is not None:
                            m |= g.whole()
            return m

        def whole(self):
            if self._all is None:
                self._all = self.range_mask(0, 10**9)
            return self._all

        def owner(self, line):
            best = None
            for s in self.st:
                if s[0] <= line <= s[1] and (best is None or s[0] >= best[0]):
                    best = s
            return best

        def scope_of(self, line):
            best = None
            for s in self.sc:
                if s[0] <= line <= s[1] and (best is None or s[0] >= best[0]):
                    best = s
            return best

        def stmt_mask(self, st, line=None):
            start, end, kind = st[0], st[1], st[2]
            name = st[3] if len(st) > 3 else ""
            m = 0
            if kind == 1:  # def/class header: anything that runs inside it
                if start in self.line_mask:
                    m |= sets[self.line_mask[start]]
                sc = next((x for x in self.sc if x[0] == start), None)
                return m | self.range_mask(start, sc[1] if sc else end)
            m = self.range_mask(start, end)
            # a changed line that only runs at import (e.g. a table entry) acts through data flow
            line_import_only = line is not None and line in self.imp and line not in self.line_mask
            if (m == 0 and any(x in self.imp for x in range(start, end + 1))) or line_import_only:
                sc = self.scope_of(start)
                if sc and not sc[2]:
                    m |= self.range_mask(sc[0], sc[1])
                else:
                    if sc and sc[2] and len(sc) > 3:
                        cm = 0
                        for rp, a, b in cov["refs"].get(sc[3], ()):
                            g = get(rp)
                            if g is not None:
                                cm |= g.range_mask(a, b)
                        if self.family_mask:
                            cm &= self.family_mask
                        m |= cm
                    rm = 0
                    if name and ATTR_NAME.match(name):
                        for rp, a, b in cov["refs"].get(name, ()):
                            g = get(rp)
                            if g is not None:
                                rm |= g.range_mask(a, b)
                        if self.family_mask:
                            rm &= self.family_mask
                        m |= rm | self.range_mask(sc[0], sc[1]) if sc else rm
                    else:
                        m |= self.whole() | self.family_mask
            return m

    fcache = {}

    def get(path):
        if path not in fcache:
            fcache[path] = F(files[path]) if path in files else None
        return fcache[path]

    def skippable(text):
        s = text.strip()
        return not s or s.startswith("#")

    risky = set()

    def sqlglot_py(path, edits):
        f = get(path)
        if f is None:
            return set()
        f.family_mask = f.family_mask_all(path)
        mask = 0
        for kind, ln, text in edits:
            if skippable(text):
                continue
            for sc_ in f.sc:
                if len(sc_) > 4 and sc_[4] and sc_[0] <= ln <= sc_[1]:
                    mask |= f.range_mask(sc_[0], sc_[1])  # cached results: later tests never reach the line
        pool_tests = path == "sqlglot/serde.py" or (
            path == "sqlglot/expressions/core.py"
            and any(525 <= ln <= 545 or 885 <= ln <= 905 for _, ln, _ in edits)
        )
        for kind, ln, text in edits:
            if skippable(text):
                continue
            if kind == "r":
                st0 = f.owner(ln)
                if st0 is None or any(x in f.imp for x in range(st0[0], st0[1] + 1)):
                    risky.add(path)
                nm = ATTR.match(text)
                if nm and (f.start_imp(ln) or True):
                    rm = 0
                    for rp, a, b in cov["refs"].get(nm.group(1), ()):
                        g = get(rp)
                        if g is not None:
                            rm |= g.range_mask(a, b)
                    if path.startswith(FAMILY) and ln not in f.line_mask:
                        fam = f.family_mask_all(path)
                        rm &= fam
                    mask |= rm
                st = f.owner(ln)
                if st is not None:
                    mask |= f.stmt_mask(st, ln)
            else:
                sc0 = f.scope_of(ln)
                if sc0 is None or sc0[2]:
                    risky.add(path)
                for l2 in (ln - 1, ln):
                    st = f.owner(l2)
                    if st is not None:
                        mask |= f.stmt_mask(st)
                sc = f.scope_of(ln)
                if sc:
                    mask |= f.range_mask(sc[0], sc[1])
                    if sc[2]:
                        mask |= f.whole()
                else:
                    mask |= f.whole()
        res = to_numbers(mask)
        if pool_tests:
            res |= {n for n in all_tests if by_number[n]["file"] == "tests/test_optimizer.py"
                    or "execute_tpc" in by_number[n]["id"]}
        if path.startswith(("sqlglot/dialects/", "sqlglot/parsers/", "sqlglot/generators/")):
            for st_ in [Path(path).stem] + cov.get("deps", {}).get(Path(path).stem, []):
                res |= file_tests.get(f"tests/dialects/test_{st_}.py", set())
        return res

    no_heavy = {t["number"] for t in tests if t["seconds"] < 3.0}
    optimizer_tests = file_tests.get("tests/test_optimizer.py", set())

    def fixture_tests(path):
        stem = Path(path).stem
        if path.startswith("tests/fixtures/optimizer/"):
            names = {stem, stem.split("__")[0], re.sub(r"_ddl$", "", stem)}
            names |= {n.rstrip("s") for n in names}
            picked = {
                n for n in optimizer_tests
                if any(("test_" + nm) in by_number[n]["id"].split("::")[-1] for nm in names)
            }
            picked |= {n for n in optimizer_tests if by_number[n]["id"].endswith("::test_optimize")}
            return picked or optimizer_tests
        return no_heavy

    def hedge(path, edits):
        """Comment-only edit: not promised harmless, so run a few cheap tests near it."""
        f = get(path) if path.startswith("sqlglot/") else None
        if f is None:
            return set()
        mask = 0
        for _, ln, _ in edits:
            for l2 in (ln - 1, ln, ln + 1):
                st = f.owner(l2)
                if st is not None:
                    mask |= f.range_mask(st[0], st[1])
        picked, spent = set(), 0.0
        for n in sorted(to_numbers(mask), key=lambda n: by_number[n]["seconds"]):
            if spent + by_number[n]["seconds"] > HEDGE_SECONDS:
                break
            picked.add(n)
            spent += by_number[n]["seconds"]
        return picked

    def select(path, edits):
        if path.endswith(DOC_SUFFIXES):
            return set()
        if path.endswith(".py") and all(skippable(t) for _, _, t in edits):
            return hedge(path, edits)
        if path.startswith("sqlglot/") and path.endswith(".py"):
            return sqlglot_py(path, edits)
        if path.startswith("tests/fixtures/"):
            if path in cov.get("fixtures", {}):
                got = {num_by_id[i] for i in cov["fixtures"][path] if i in num_by_id}
                if path.startswith("tests/fixtures/optimizer/") and path.endswith(".sql"):
                    got |= fixture_tests(path)
                return got
            return fixture_tests(path)
        if path.startswith("tests/") and path.endswith(".py"):
            if Path(path).name.startswith("test_"):
                return file_tests.get(path) or no_heavy
            return all_tests
        return all_tests

    def split(chosen):
        ordered = sorted(chosen, key=lambda n: by_number[n]["seconds"], reverse=True)
        best, best_cost = [], None
        for count in range(1, min(MAX_WORKERS, len(ordered)) + 1):
            workers = [[] for _ in range(count)]
            loads = [0.0] * count
            for n in ordered:
                i = loads.index(min(loads))
                workers[i].append(n)
                loads[i] += by_number[n]["seconds"]
            cost = max(loads) + WORKER_COST * count
            if best_cost is None or cost < best_cost:
                best, best_cost = workers, cost
        return best

    for patch in sorted((DATA / "commits").glob("*.patch")):
        text = patch.read_text(encoding="utf-8", errors="replace")
        chosen = set()
        risky.clear()
        for path, edits in parse_patch(text).items():
            chosen |= select(path, edits)
        if risky and len(chosen) < len(all_tests):
            try:
                verdict = importcheck.imports_ok(text, sorted(risky))
            except Exception:
                verdict = None
            if verdict is False:
                if all(p.startswith(FAMILY) for p in risky):
                    for p in risky:
                        for d in FAMILY:
                            g = get(d + Path(p).name)
                            if g is not None:
                                chosen |= to_numbers(g.whole())
                        chosen |= file_tests.get(f"tests/dialects/test_{Path(p).stem}.py", set())
                else:
                    chosen = set(all_tests)
        kinds = set()
        parsed = parse_patch(text)
        if any(p.startswith("tests/fixtures/") for p in parsed):
            kinds.add("fixture")
        if parsed and all(
            p.endswith(DOC_SUFFIXES) or (p.endswith(".py") and all(skippable_line(t_) for _, _, t_ in e))
            for p, e in parsed.items()
        ):
            kinds.add("comment")
        if risky:
            kinds.add("risky")
        if kinds & PROBE:
            chosen = set(all_tests)
        if len(chosen) >= 0.6 * len(all_tests):
            chosen = set(all_tests)  # a collection-time crash fails whole files
        print(json.dumps({"commit": patch.stem, "workers": split(chosen)}))


if __name__ == "__main__":
    main()
