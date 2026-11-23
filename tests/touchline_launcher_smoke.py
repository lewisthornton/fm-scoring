"""Cross-platform production launcher smoke, including Windows CMD path quoting."""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from touchline_fixture import create, ROOT, CAREER


def main():
    with tempfile.TemporaryDirectory(prefix="touchline launch ") as temp:
        root = Path(temp) / "invented generations"
        first, _ = create(root)
        checkout = Path(temp) / "checkout with spaces"
        checkout.mkdir()
        for file in ("touchline_launch.py", "touchline_server.py", "touchline_generation.py", "launch-touchline.cmd"):
            shutil.copy2(ROOT / file, checkout / file)
        shutil.copytree(ROOT / "touchline/dist", checkout / "touchline/dist")
        env = os.environ.copy()
        env["PATH"] = str(Path(sys.executable).parent)
        if os.name == "nt":
            env["PATH"] += os.pathsep + str(Path(os.environ["SystemRoot"]) / "System32")
            help_result = subprocess.run([env["COMSPEC"], "/d", "/c", "call", str(checkout / "launch-touchline.cmd"), "--help"],
                                         env=env, capture_output=True, text=True, timeout=20)
            assert help_result.returncode == 0 and "--generations" in help_result.stdout, help_result
        assert shutil.which("node", path=env["PATH"]) is None
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cmd = [sys.executable, str(checkout / "touchline_launch.py"), "--generations", str(root),
               "--career", CAREER, "--port", str(port), "--no-browser"]
        with subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0) as proc:
            try:
                url = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        raise AssertionError(proc.communicate())
                    try:
                        with urlopen(url + "/api/current", timeout=1) as response:
                            assert json.load(response)["generation_id"] == first
                        break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise AssertionError("Launcher did not become ready")
                with urlopen(url, timeout=5) as response:
                    assert b"Touchline" in response.read()
                duplicate_cmd = cmd if os.name != "nt" else [env["COMSPEC"], "/d", "/c", "call",
                    str(checkout / "launch-touchline.cmd"), *cmd[2:]]
                duplicate = subprocess.run(duplicate_cmd, env=env, capture_output=True, text=True, timeout=20)
                assert duplicate.returncode != 0 and "port" in duplicate.stderr
                proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
                assert proc.wait(timeout=15) == 0
                print("Production launcher ready and stopped cleanly; duplicate refused; Node absent from PATH.")
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=10)
        invalid = subprocess.run([*cmd, "--dist", str(checkout / "missing")], env=env, capture_output=True, text=True, timeout=20)
        assert invalid.returncode != 0 and "bundle missing" in invalid.stderr


if __name__ == "__main__":
    main()
