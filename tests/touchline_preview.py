"""Run a temporary invented-data Touchline server for browser CI."""
import tempfile
import os
from pathlib import Path
from touchline_fixture import create, CAREER, ROOT
from touchline_server import make_server, Store

with tempfile.TemporaryDirectory() as temp:
    root = Path(os.environ.get("TOUCHLINE_FIXTURE_DIR", temp)) / "generations"
    create(root)
    with make_server(Store(root, CAREER), ROOT / "touchline" / "dist") as server:
        server.serve_forever()
