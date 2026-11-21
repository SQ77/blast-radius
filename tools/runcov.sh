set -e
cd /work/sqlglot
pip install -q -r /work/req.txt coverage pytest-cov 2>&1 | tail -2
export PYTHONPATH=/work/sqlglot SKIP_INTEGRATION=0
python -m pytest tests -q -p no:cacheprovider -p syncpool --cov=sqlglot --cov-context=test --cov-report= -o addopts="" --timeout=600 2>&1 | tail -15
cp .coverage /work/cov2.db
