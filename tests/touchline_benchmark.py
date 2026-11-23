"""Repeatable invented generation benchmark, no personal data or external requests."""
import argparse
import json
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path

from touchline_fixture import create, CAREER
from touchline_server import Store
import touchline_generation as generation


def measure(fn, repeats=3):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        result = fn()
        samples.append((time.perf_counter() - start) * 1000)
    return result, round(statistics.median(samples), 2)


def benchmark(root, squad, targets):
    start = time.perf_counter()
    first, second = create(root, squad, targets)
    build_seconds = round(time.perf_counter() - start, 2)
    _, validate_ms = measure(lambda: generation.read_generation(root / "generations" / first))
    store = Store(root, CAREER)
    overview = store.data("overview", first)["data"]
    candidate = next(p for p in overview["recommendations"] if p["classification"] != "already_in_squad")
    slot = candidate["selected_slot_id"] or "lb"
    result = {"squad": squad, "targets": targets, "build_seconds": build_seconds, "validation_ms": validate_ms}
    result["cache_admitted"] = bool(store._cache)
    uncached = Store(root, CAREER, cache_entries=0)
    for route, kwargs in (("overview", {}), ("slot", {"slot": slot}), ("candidates", {"slot": slot}), ("signing", {"player": candidate["player_id"]})):
        body, latency = measure(lambda: json.dumps(store.data(route, first, **kwargs), ensure_ascii=False, separators=(",", ":")).encode())
        before, baseline_ms = measure(lambda: json.dumps(uncached.data(route, first, **kwargs), ensure_ascii=False, separators=(",", ":")).encode())
        assert body == before
        result[route] = {"uncached_ms": baseline_ms, "cached_ms": latency, "bytes": len(body)}
    result["history_artifact_bytes"] = (root / "generations" / first / generation.HISTORY_FILE).stat().st_size
    for route in ("profile", "history", "benchmark"):
        body, latency = measure(lambda: generation.canonical(store.data(route, first, player=candidate["player_id"])))
        assert len(body) <= 512 * 1024
        result[route] = {"median_ms": latency, "bytes": len(body)}
    _, result["switch_ms"] = measure(lambda: store.data("overview", second))
    tracemalloc.start()
    probe = Store(root, CAREER)
    probe.data("overview", first)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result["load_traced_peak_bytes"] = peak
    result["retained_traced_bytes"] = current
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", choices=("small", "medium", "large"), default="small")
    args = parser.parse_args()
    counts = {"small": (9, 19), "medium": (45, 80), "large": (60, 500)}
    with tempfile.TemporaryDirectory() as temp:
        print(json.dumps(benchmark(Path(temp), *counts[args.size]), indent=2))
