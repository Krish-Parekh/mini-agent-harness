import tempfile

from support import load, stub

stub("logfire")
load("src.services.ingestion.loaders.base", "src/services/ingestion/loaders/base.py")
text = load("text_loader", "src/services/ingestion/loaders/text.py")

with tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False) as handle:
    handle.write("café ok".encode("latin-1"))

content = text.TextLoader().parse(handle.name)
if "caf" not in content or "ok" not in content:
    raise SystemExit(f"unexpected content {content!r}")
