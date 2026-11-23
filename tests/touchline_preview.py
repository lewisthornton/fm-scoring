"""Run a temporary invented-data Touchline server for browser CI."""
import tempfile
import os
from pathlib import Path
from touchline_fixture import create, CAREER, ROOT
from touchline_server import make_server, Store

with tempfile.TemporaryDirectory() as temp:
    root = Path(os.environ.get("TOUCHLINE_FIXTURE_DIR", temp)) / "generations"
    counts = {"small": (9, 19), "medium": (45, 80), "large": (60, 500)}
    create(root, *counts[os.environ.get("TOUCHLINE_BENCH_SIZE", "small")], changed_slot=True)
    with make_server(Store(root, CAREER), ROOT / "touchline" / "dist") as server:
        server.serve_forever()
