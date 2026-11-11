import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
FAQ_PATH = ROOT / "data" / "faq" / "faq.jsonl"
EVAL_PATH = ROOT / "tests" / "fixtures" / "faq_eval_colloquial.jsonl"
SCRIPT = ROOT / "scripts" / "eval_colloquial.py"

SUMMARY_RE = re.compile(
    r"^n=\d+ n_answerable=\d+ n_none=\d+ top1=\d\.\d{3} top3=\d\.\d{3} none_correct=\d\.\d{3} "
    r"overall_top1=\d\.\d{3} leak_mean=\d\.\d{3} leak_p50=\d\.\d{3} top1_low_leak=\d\.\d{3} "
    r"n_low_leak=\d+ top1_high_leak=\d\.\d{3} n_high_leak=\d+$"
)


def _require(path: Path) -> None:
    if not path.exists():
        pytest.fail(f"missing {path.relative_to(ROOT)}")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    _require(FAQ_PATH)
    _require(EVAL_PATH)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--faq", str(FAQ_PATH), "--eval", str(EVAL_PATH), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )


@pytest.fixture(scope="module")
def ec() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_colloquial_data", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_colloquial_fixture_schema_ok() -> None:
    proc = _run("--validate")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip().startswith("SCHEMA OK n=")


def test_colloquial_measurement_runs() -> None:
    proc = _run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines
    print(lines[0])
    assert SUMMARY_RE.match(lines[0]), lines[0]
    assert lines[-1] == "RESULT MEASURED"


def test_leak_identical_is_one(ec: ModuleType) -> None:
    assert ec.leak("어린이 예방접종", "어린이 예방접종") == 1.0
