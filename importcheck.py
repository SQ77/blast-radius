"""Apply a patch's sqlglot edits in memory and try to import the result."""
import json
import subprocess
import sys

SRC = "/app/src"

RUNNER = r'''
import importlib.abc, importlib.util, json, sys
over = json.loads(sys.stdin.read())
mods = {}
for rel, text in over.items():
    name = rel[:-3].replace("/", ".")
    if name.endswith(".__init__"):
        name = name[:-9]
    mods[name] = (rel, text)

class L(importlib.abc.SourceLoader):
    def __init__(self, name, rel, text):
        self.name, self.rel, self.text = name, rel, text
    def get_filename(self, fullname):
        return "/app/src/" + self.rel
    def get_data(self, path):
        return self.text.encode()
    def path_stats(self, path):
        raise OSError
    def set_data(self, *a, **k):
        pass

class F(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name in mods:
            rel, text = mods[name]
            return importlib.util.spec_from_loader(name, L(name, rel, text), is_package=rel.endswith("__init__.py"))
        return None

sys.meta_path.insert(0, F())
sys.path.insert(0, "/app/src")
import sqlglot
for n in mods:
    __import__(n)
'''


def apply_hunks(orig: str, hunks):
    lines = orig.split("\n")
    out, pos = [], 0
    for start, body in hunks:
        out.extend(lines[pos:start - 1])
        pos = start - 1
        for l in body:
            tag, text = l[:1], l[1:]
            if tag == " ":
                if lines[pos] != text:
                    return None
                out.append(text)
                pos += 1
            elif tag == "-":
                if lines[pos] != text:
                    return None
                pos += 1
            elif tag == "+":
                out.append(text)
    out.extend(lines[pos:])
    return "\n".join(out)


def parse_hunks(patch_text):
    import re
    files, cur, hunk = {}, None, None
    rows = patch_text.split("\n")
    n = len(rows)
    for idx, line in enumerate(rows):
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(\S+) b/(\S+)", line)
            cur = m.group(1) if m else None
            hunk = None
            if cur:
                files[cur] = []
        elif line.startswith("@@") and cur:
            m = re.match(r"@@ -(\d+)", line)
            hunk = (int(m.group(1)), [])
            files[cur].append(hunk)
        elif cur and hunk is not None and line[:1] in (" ", "-", "+"):
            hunk[1].append(line)
        elif cur and hunk is not None and line == "" and idx < n - 1:
            hunk[1].append(" ")  # blank context line stripped of its space
    return files


def imports_ok(patch_text, paths):
    """True if the patched modules import; False if they crash; None if we could not tell."""
    hunks = parse_hunks(patch_text)
    over = {}
    for p in paths:
        try:
            orig = open(f"{SRC}/{p}", encoding="utf-8").read()
        except OSError:
            return None
        new = apply_hunks(orig, hunks.get(p, []))
        if new is None:
            return None
        over[p] = new
    try:
        r = subprocess.run([sys.executable, "-c", RUNNER], input=json.dumps(over), text=True,
                           capture_output=True, timeout=60)
    except Exception:
        return None
    return r.returncode == 0


def comment_edit_is_real(path, edits):
    """True if an edit that looks like a comment/blank line could change behaviour:
    it sits inside a (non-docstring) multi-line string, after a backslash continuation,
    or we cannot read the source to check."""
    import ast
    try:
        src = open(f"{SRC}/{path}", encoding="utf-8").read()
        tree = ast.parse(src)
    except Exception:
        return True
    lines = src.split("\n")
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            b = node.body
            if b and isinstance(b[0], ast.Expr) and isinstance(getattr(b[0], "value", None), ast.Constant) \
                    and isinstance(b[0].value.value, str):
                doc_ids.add(id(b[0].value))
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Constant, ast.JoinedStr)) and id(node) not in doc_ids:
            if isinstance(node, ast.Constant) and not isinstance(node.value, (str, bytes)):
                continue
            if node.end_lineno > node.lineno:
                spans.append((node.lineno, node.end_lineno))
    for kind, ln, _ in edits:
        for a, b in spans:
            # removed line ln, or insertion before old line ln
            if (kind == "r" and a <= ln <= b) or (kind == "a" and a < ln <= b):
                return True
        prev = lines[ln - 2] if 2 <= ln <= len(lines) + 1 else ""
        if prev.rstrip().endswith("\\"):
            return True
    return False
