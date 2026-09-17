"""Verify units, platform fallbacks and the source-line counting convention."""

import importlib.util
import io
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def load_tool(name):
    path = Path(__file__).resolve().parents[1] / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def system_info():
    return load_tool("system_info")


def test_macos_cpu_model_and_failure_fallback(system_info):
    with patch.object(system_info.platform, "system", return_value="Darwin"):
        with patch.object(
            system_info.subprocess,
            "run",
            return_value=SimpleNamespace(stdout="Apple M2\n"),
        ) as run:
            assert system_info.cpu_model() == "Apple M2"
            assert run.call_args.args[0] == [
                "sysctl",
                "-n",
                "machdep.cpu.brand_string",
            ]
        with patch.object(
            system_info.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("sysctl", 3),
        ):
            with patch.object(
                system_info.platform, "processor", return_value="arm"
            ):
                assert system_info.cpu_model() == "arm"
        with patch.object(
            system_info.subprocess,
            "run",
            return_value=SimpleNamespace(stdout=""),
        ):
            with patch.object(
                system_info.platform, "processor", return_value="arm"
            ):
                assert system_info.cpu_model() == "arm"


def test_linux_cpu_and_unknown_architecture_fallback(system_info):
    with patch.object(system_info.platform, "system", return_value="Linux"):
        with patch(
            "builtins.open",
            return_value=io.StringIO("processor : 0\nmodel name : Test CPU\n"),
        ):
            assert system_info.cpu_model() == "Test CPU"
        with patch("builtins.open", side_effect=OSError("missing")):
            with patch.object(
                system_info.platform, "processor", return_value=""
            ):
                with patch.object(
                    system_info.platform, "machine", return_value="x86_64"
                ):
                    assert system_info.cpu_model() == "x86_64"
    with patch.object(system_info.platform, "system", return_value="Windows"):
        with patch.object(system_info.platform, "processor", return_value=""):
            with patch.object(
                system_info.platform, "machine", return_value=""
            ):
                assert system_info.cpu_model() == "unavailable"


@pytest.mark.parametrize(
    "system,expected", [("Darwin", 4096), ("Linux", 4194304)]
)
def test_process_rss_units(system_info, system, expected):
    import resource

    with patch.object(system_info.platform, "system", return_value=system):
        with patch.object(
            resource, "getrusage", return_value=SimpleNamespace(ru_maxrss=4096)
        ):
            assert system_info.peak_process_bytes() == expected


def test_process_rss_unavailable_and_machine_report(system_info):
    import builtins

    original = builtins.__import__

    def missing_resource(name, *args, **kwargs):
        if name == "resource":
            raise ImportError(name)
        return original(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=missing_resource):
        assert system_info.peak_process_bytes() is None
    report = system_info.machine_info()
    assert report["python"]
    assert report["processor"]
    assert "high-water" in report["rss_scope"]


def test_counter_distinguishes_docstrings_from_runtime_strings(tmp_path):
    counter = load_tool("count_lines")
    path = tmp_path / "example.py"
    path.write_text(
        '"""Module documentation.\nSecond line."""\n'
        "# a comment\n\n"
        'VALUE = """runtime\ntext"""\n'
        "def greeting():\n"
        '    """Function documentation."""\n'
        "    return VALUE  # a real statement\n"
    )
    result = counter.count_file(path)
    assert result == {"physical": 9, "nonempty": 8, "docstring": 3, "code": 4}


def test_counter_excludes_dependencies_data_and_markdown(tmp_path):
    counter = load_tool("count_lines")
    for folder in ("arena", "tests", "tools", "venv", "docs"):
        (tmp_path / folder).mkdir()
    (tmp_path / "arena/a.py").write_text("x = 1\n")
    (tmp_path / "tests/test_a.py").write_text("assert 1 == 1\n")
    (tmp_path / "tools/measure.py").write_text("print(1)\n")
    (tmp_path / "venv/dependency.py").write_text("x = 1\n" * 100)
    (tmp_path / "docs/README.md").write_text("Documentation\n")
    report = counter.report(tmp_path)
    assert report["totals"]["code"] == 3
    assert set(report["files"]) == {
        "arena/a.py",
        "tests/test_a.py",
        "tools/measure.py",
    }


def test_code_style_does_not_exceed_course_line_limit():
    root = Path(__file__).resolve().parents[1]
    violations = [
        f"{path.relative_to(root)}:{number}"
        for path in (root / "arena").rglob("*.py")
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if len(line) > 80
    ]
    assert violations == []
