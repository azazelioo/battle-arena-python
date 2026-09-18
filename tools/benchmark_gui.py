from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
import sys
import tempfile
import time
import tracemalloc
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from arena.application.controller import GameController, MatchSetup
from arena.presentation.gui import ArenaWindow
from system_info import machine_info, peak_process_bytes


def widget_count(widget: tk.Misc) -> int:
    return 1 + sum(widget_count(child) for child in widget.winfo_children())


def measure(cycles: int = 100) -> dict[str, object]:
    if type(cycles) is not int or cycles < 1:
        raise ValueError("At least one cycle is required")
    root = tk.Tk()
    root.withdraw()
    try:
        with tempfile.TemporaryDirectory(
            prefix="arena-gui-benchmark-"
        ) as name:
            controller = GameController(Path(name))
            app = ArenaWindow(root, controller)
            root.update()
            baseline_widgets = widget_count(root)
            peak_before = peak_process_bytes()
            samples = []
            counts = []
            pending = []
            tracemalloc.start()
            try:
                for _ in range(cycles):
                    start = time.perf_counter()
                    controller.new_match(MatchSetup())
                    app.battle()
                    app.pause()
                    app.setup()
                    app.rules()
                    app.settings()
                    app.menu()
                    root.update()
                    gc.collect()
                    samples.append((time.perf_counter() - start) * 1000)
                    counts.append(widget_count(root))
                    pending.append(len(root.tk.call("after", "info")))
                current, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            result = {
                "machine": machine_info(),
                "tk_version": str(root.tk.call("info", "patchlevel")),
                "cycles": cycles,
                "screens_per_cycle": 6,
                "max_cycle_ms": max(samples),
                "widgets_before": baseline_widgets,
                "widgets_after": counts[-1],
                "widget_count_range": [min(counts), max(counts)],
                "no_widget_growth": all(n == baseline_widgets for n in counts),
                "pending_callbacks_range": [min(pending), max(pending)],
                "no_pending_callbacks": not any(pending),
                "python_current_bytes": current,
                "python_peak_bytes": peak,
                "process_peak_rss_before": peak_before,
                "process_peak_rss_after": peak_process_bytes(),
                "memory_note": (
                    "RSS is a high-water mark, not a proof of absence of leaks. "
                    "Widget and callback counts check retained GUI resources."
                ),
            }
            app.cancel_bot()
            controller.abandon()
            return result
    finally:
        root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=100)
    args = parser.parse_args()
    print(json.dumps(measure(args.cycles), indent=2))


if __name__ == "__main__":
    main()
