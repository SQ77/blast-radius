"""Add fixture -> test ids to covmap.json from reads.jsonl (made by fileaudit.py)."""
import json, sys
reads, tj, cmap = sys.argv[1:4]
tests = json.load(open(tj))["tests"]
ids = [t["id"] for t in tests]
r = json.load(open(reads))
fx = {}
for p, node, phase in r:
    if not p.startswith("fixtures/"):
        continue
    if phase == "call":
        sel = {node}
        if not p.startswith("fixtures/optimizer/") or not p.endswith(".sql"):
            # fixture loaders are cached, so later readers go unseen: take the whole file
            f = node.split("::")[0]
            sel = {i for i in ids if i.startswith(f + "::")}
    elif phase == "setup":
        # class/module-level setup is shared by every test in the file
        f = node.split("::")[0]
        sel = {i for i in ids if i.startswith(f + "::")}
    else:
        sel = {i for i in ids if i.startswith(node)}
    fx.setdefault("tests/" + p, set()).update(sel)
m = json.load(open(cmap))
m["fixtures"] = {k: sorted(v) for k, v in fx.items()}
json.dump(m, open(cmap, "w"), separators=(",", ":"))
print(len(fx))
