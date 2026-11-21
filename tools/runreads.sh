cd /work/sqlglot
pip install -q -r /work/req.txt 2>&1 | grep -v -i "notice\|warning"
export PYTHONPATH=/work/sqlglot SKIP_INTEGRATION=0
python -m pytest tests -q -p no:cacheprovider -p syncpool -p fileaudit -o addopts="" 2>&1 | tail -3
