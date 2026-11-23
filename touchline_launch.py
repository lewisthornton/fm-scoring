"""Opt-in local Touchline launcher; never runs the watcher or opens a save."""
import argparse
import sys
import signal
import threading
import webbrowser
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generations", required=True, type=Path)
    parser.add_argument("--career", required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dist", type=Path, default=Path(__file__).resolve().parent / "touchline" / "dist")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required.")
    from touchline_server import Store, APIError, make_server
    if not args.generations.is_dir():
        parser.error("Generation directory does not exist. Publish with the separate M1a command first.")
    if not (args.dist / "index.html").is_file() or not any((args.dist / "assets").glob("*.js")):
        parser.error("Production frontend bundle missing. Install the matching dist bundle from CI or build it separately.")
    if not 1 <= args.port <= 65535:
        parser.error("Choose a port between 1 and 65535.")
    store = Store(args.generations, args.career)
    try:
        store.load()
    except APIError as exc:
        parser.error(f"Cannot validate current generation ({exc.code}). Check career and generation directory; publish or roll back explicitly.")
    try:
        server = make_server(store, args.dist, args.port)
    except ValueError as exc:
        parser.error(f"Production frontend invalid: {exc}. Install the matching dist bundle.")
    except OSError as exc:
        parser.error(f"Could not listen on port {args.port}. Close the existing instance or choose another port ({exc}).")
    with server:
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, signal.default_int_handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            print(f"Touchline ready: {url} — Ctrl+C to stop", flush=True)
            if not args.no_browser:
                try:
                    if not webbrowser.open(url):
                        print(f"Open {url} in your browser.", flush=True)
                except (webbrowser.Error, OSError):
                    print(f"Open {url} in your browser.", flush=True)
            while worker.is_alive():
                worker.join(timeout=0.25)
        except KeyboardInterrupt:
            print("Stopping Touchline.", flush=True)
        finally:
            server.shutdown()
            worker.join()
    return 0


def run(argv=None):
    try:
        return main(argv)
    except KeyboardInterrupt:
        print("Touchline startup cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(run())
