import os, sys, json, atexit
import syncpool  # noqa
OUT = "/work/reads.jsonl"
cur = {"collect": None}
rec = set()
ROOT = "/work/sqlglot/tests/"

def hook(event, args):
    if event != "open":
        return
    p = args[0]
    if not isinstance(p, str) or not p.startswith(ROOT) or p.endswith((".pyc",)):
        return
    t = os.environ.get("PYTEST_CURRENT_TEST")
    if t:
        nodeid, _, phase = t.rpartition(" (")
        rec.add((p[len(ROOT):], nodeid, phase.rstrip(")")))
    elif cur["collect"]:
        rec.add((p[len(ROOT):], cur["collect"], "collect"))

sys.addaudithook(hook)

def pytest_collectstart(collector):
    cur["collect"] = getattr(collector, "nodeid", None)

def pytest_sessionfinish(session):
    with open(OUT, "w") as f:
        json.dump(sorted(rec), f)
