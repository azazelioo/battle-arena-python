"""Identify the measured machine and distinguish process RSS from Python memory."""

from __future__ import annotations

import platform
import subprocess


def cpu_model() -> str:
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                check=True,
                timeout=3,
            )
            if result.stdout.strip():
                return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    elif platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as stream:
                for line in stream:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine() or "unavailable"


def peak_process_bytes() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if platform.system() == "Darwin" else value * 1024)


def machine_info() -> dict[str, object]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": cpu_model(),
        "process_peak_rss_bytes": peak_process_bytes(),
        "rss_scope": "OS process high-water mark; includes native libraries",
    }
