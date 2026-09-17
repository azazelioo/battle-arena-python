"""Reproducible engine latency and bounded-history Python memory measurements."""

from __future__ import annotations

import gc
import json
import platform
import statistics
import time
import tracemalloc
from system_info import machine_info
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from arena.application.bot import AggressiveBot
from arena.domain.battle import BattleEngine
from arena.domain.character import Character
from arena.domain.model import ActionRequest, History, Phase


def fresh() -> BattleEngine:
    return BattleEngine(
        Character("p1", "A", "ranger"), Character("p2", "B", "mage")
    )


def benchmark() -> dict[str, object]:
    samples = []
    event_counts = []
    for index in range(1000):
        engine = fresh()
        snapshot = engine.snapshot()
        if index % 3 == 0:
            request = ActionRequest(snapshot.match_id, 0, "p1", "attack", "p2")
        else:
            request = ActionRequest(
                snapshot.match_id,
                1,
                "p1",
                "poison_arrow" if index % 3 == 1 else "attack",
                "p2",
            )
        start = time.perf_counter()
        engine.submit(request)
        state = engine.snapshot()
        samples.append((time.perf_counter() - start) * 1000)
        event_counts.append(len(state.events))
    del engine, snapshot, state
    gc.collect()
    tracemalloc.start()
    history: History[object] = History(50)
    for _ in range(100):
        engine = fresh()
        while engine.snapshot().phase != Phase.FINISHED:
            snapshot = engine.snapshot()
            request = AggressiveBot().choose_action(
                snapshot, engine.action_options(snapshot.active_id)
            )
            engine.submit(request)
        history.append(engine.snapshot())
        del engine, snapshot
    gc.collect()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    ordered = sorted(samples)
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": machine_info()["processor"],
        "system": machine_info(),
        "commands": len(samples),
        "event_count_range": [min(event_counts), max(event_counts)],
        "latency_ms": {
            "median": statistics.median(samples),
            "p95": ordered[949],
            "max": max(samples),
        },
        "under_500_ms": max(samples) < 500,
        "memory_100_matches": {
            "retained_matches": len(history),
            "current_bytes": current,
            "peak_bytes": peak,
        },
        "memory_scope": "Python allocations only; excludes Tcl/Tk and OS process memory",
    }


if __name__ == "__main__":
    print(json.dumps(benchmark(), indent=2))
