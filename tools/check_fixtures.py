"""Regression check: TPC fixtures must map to the executor TPC tests.
Usage: python tools/check_fixtures.py covmap.json sample/tests.json"""
import json, sys
cov = json.load(open(sys.argv[1]))
ids = {t["id"] for t in json.load(open(sys.argv[2]))["tests"]}
need = {"tests/test_executor.py::TestExecutor::test_execute_tpch",
        "tests/test_executor.py::TestExecutor::test_execute_tpcds"}
need = {n for n in need if n in ids} or {i for i in ids if "execute_tpc" in i}
bad = 0
for p, got in cov["fixtures"].items():
    if "tpc-" in p and not need <= set(got):
        print("MISSING", p, need - set(got)); bad += 1
print("fixtures checked:", sum("tpc-" in p for p in cov["fixtures"]), "bad:", bad)
sys.exit(1 if bad else 0)
