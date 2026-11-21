"""Build step: download sqlglot's package at the pinned commit into /app/src (rules allow this)."""
import io, sys, tarfile, urllib.request

SHA = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
data = urllib.request.urlopen(f"https://codeload.github.com/tobymao/sqlglot/tar.gz/{SHA}", timeout=120).read()
with tarfile.open(fileobj=io.BytesIO(data)) as tar:
    for m in tar.getmembers():
        parts = m.name.split("/", 1)
        if len(parts) == 2 and parts[1].startswith("sqlglot/") and (m.isdir() or m.name.endswith((".py", ".typed"))):
            m.name = parts[1]
            tar.extract(m, sys.argv[1])
