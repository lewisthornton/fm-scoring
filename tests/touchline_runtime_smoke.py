"""Production bundle smoke with Node absent from the server subprocess PATH."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from touchline_fixture import create, ROOT, CAREER


def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "generations"
        first, _ = create(root)
        env = os.environ.copy()
        env["PATH"] = temp
        with subprocess.Popen([sys.executable, str(ROOT / "touchline_server.py"), "--generations", str(root),
                               "--career", CAREER, "--port", "0"], stdout=subprocess.PIPE,
                              text=True, env=env) as proc:
            try:
                url = proc.stdout.readline().strip().split()[-1]
                assert url.startswith("http://127.0.0.1:")
                def get(route, **params):
                    start = time.perf_counter()
                    with urlopen(url + route + "?" + urlencode(params) if params else url + route, timeout=20) as response:
                        data = response.read()
                    return data, round((time.perf_counter() - start) * 1000, 2)
                html, load_ms = get("/")
                assert b"Touchline" in html
                import re
                assets = re.findall(rb'(?:src|href)="(/assets/[^"]+)"', html)
                assert assets
                for asset in assets:
                    content, _ = get(asset.decode())
                    assert content
                overview, overview_ms = get("/api/overview", generation=first)
                result = json.loads(overview)
                assert result["generation_id"] == first
                slot = result["data"]["recommendations"][0]["selected_slot_id"] or "lb"
                candidates, candidates_ms = get("/api/candidates", generation=first, slot=slot)
                candidate = result["data"]["recommendations"][0]["player_id"]
                signing, signing_ms = get("/api/signing", generation=first, player=candidate)
                print(json.dumps({"runtime_path_has_node": False, "html_ms": load_ms,
                                  "overview_bytes": len(overview), "overview_ms": overview_ms,
                                  "candidates_bytes": len(candidates), "candidates_ms": candidates_ms,
                                  "signing_bytes": len(signing), "signing_ms": signing_ms}, indent=2))
            finally:
                proc.terminate()
                proc.wait(timeout=10)


if __name__ == "__main__":
    main()
