"""First-draft selector: pick tests by what each patch touches.

Cost model (SCORING.md): busiest worker's seconds + 2 s per worker, and 300 s
for every commit where a failing test was left out. So the rules lean safe:
the savings come mostly from (a) skipping the handful of very slow tests
unless the patch could plausibly reach them, (b) running nothing for
comment-only edits, and (c) narrowing fixture-only edits to the matching test.
"""

import json
import re
import sys
from pathlib import Path

DATA = Path("/data")
MAX_WORKERS = 8
WORKER_COST = 2.0
HEAVY_SECONDS = 3.0  # test_max_nodes, tpcds, tpch, generator_memory

# Source areas whose changes can reach the executor / heavy optimizer tests.
OPTIMIZER_AREAS = ("optimizer/", "executor/", "planner", "schema", "lineage", "diff/", "scope")
# Top-level dirs that hold one file per dialect.
DIALECT_DIRS = ("dialects/", "parsers/", "generators/", "typing/")
DOC_SUFFIXES = (".md", ".rst", ".txt")


def changed_files(patch: str) -> dict[str, list[str]]:
    """Map each changed path to its added/removed lines."""
    files: dict[str, list[str]] = {}
    current = None
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            match = re.match(r"diff --git a/(\S+) b/(\S+)", line)
            current = match.group(2) if match else None
            if current:
                files.setdefault(current, [])
        elif current and line[:1] in "+-" and not line.startswith(("+++", "---")):
            files[current].append(line[1:])
    return files


def comment_only(path: str, lines: list[str]) -> bool:
    if not path.endswith(".py"):
        return False
    return all(not l.strip() or l.strip().startswith("#") for l in lines)


def main() -> None:
    tests = json.loads((DATA / "tests.json").read_text())["tests"]
    by_number = {t["number"]: t for t in tests}
    dialects = {
        Path(t["file"]).stem.removeprefix("test_")
        for t in tests
        if t["file"].startswith("tests/dialects/")
    }

    all_tests = {t["number"] for t in tests}
    heavy = {t["number"] for t in tests if t["seconds"] >= HEAVY_SECONDS}
    optimizer_tests = {t["number"] for t in tests if t["file"] == "tests/test_optimizer.py"}
    optimizer_heavy = {n for n in heavy if by_number[n]["file"] == "tests/test_executor.py"}
    # Heavy tests a non-optimizer change can still plausibly reach: none.
    no_heavy = all_tests - heavy

    def fixture_tests(path: str) -> set[int]:
        stem = Path(path).stem
        if path.startswith("tests/fixtures/optimizer/"):
            names = {stem, stem.split("__")[0], re.sub(r"_ddl$", "", stem)}
            names |= {name.rstrip("s") for name in names}  # pushdown_projections -> test_pushdown_projection
            picked = {
                n for n in optimizer_tests
                if any(("test_" + name) in by_number[n]["id"].split("::")[-1] for name in names)
            }
            # test_optimize runs every optimizer fixture end to end.
            picked |= {n for n in optimizer_tests if by_number[n]["id"].endswith("::test_optimize")}
            return picked or optimizer_tests
        return no_heavy

    def select(path: str, lines: list[str]) -> set[int]:
        if path.endswith(DOC_SUFFIXES):
            return set()
        if comment_only(path, lines):
            return set()
        if path.startswith("tests/fixtures/"):
            return fixture_tests(path)
        if path.startswith("tests/") and path.endswith(".py"):
            return {n for n in all_tests if by_number[n]["file"] == path} or no_heavy
        if not path.startswith("sqlglot/"):
            return all_tests  # packaging / config: be safe
        rel = path[len("sqlglot/"):]
        if any(rel.startswith(area) for area in OPTIMIZER_AREAS):
            # Reaches the executor's tpcds/tpch runs, not the parser/generator stress tests.
            return no_heavy | optimizer_heavy
        if rel.startswith(DIALECT_DIRS) and Path(rel).stem in dialects:
            return no_heavy
        return all_tests  # parser, tokens, generator, expressions, dialect base, ...

    def split(chosen: set[int]) -> list[list[int]]:
        """Best worker count by LPT, trading balance against the 2 s per worker."""
        ordered = sorted(chosen, key=lambda n: by_number[n]["seconds"], reverse=True)
        best, best_cost = [], None
        for count in range(1, min(MAX_WORKERS, len(ordered)) + 1):
            workers: list[list[int]] = [[] for _ in range(count)]
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
        chosen: set[int] = set()
        for path, lines in changed_files(text).items():
            chosen |= select(path, lines)
        print(json.dumps({"commit": patch.stem, "workers": split(chosen)}))


if __name__ == "__main__":
    main()
