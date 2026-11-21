FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
COPY tools/fetch_src.py /tmp/fetch_src.py
RUN python /tmp/fetch_src.py /app/src && python -m compileall -q /app/src && rm /tmp/fetch_src.py
COPY selector.py importcheck.py covmap.json /app/
CMD ["python", "/app/selector.py"]
