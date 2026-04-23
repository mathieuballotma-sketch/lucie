"""
Tests for the public truth rule demonstration.

These tests are an additional public sanity check one pattern shown in
examples/truth_rule_proof.py. The private test suite covers the production
Verificateur with 375 tests, most of which are not exposed here.
"""

import subprocess
import sys
from pathlib import Path

EXAMPLE = Path(__file__).parent.parent / "examples" / "truth_rule_proof.py"


def test_example_file_exists():
    """The public demonstration file must exist."""
    assert EXAMPLE.exists(), f"Missing: {EXAMPLE}"


def test_example_is_executable():
    """The demonstration runs without errors."""
    result = subprocess.run(
        [sys.executable, str(EXAMPLE)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"Demo failed with code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_example_refuses_invalid_reference():
    """Running the demo must mention a REFUSED decision at least once."""
    result = subprocess.run(
        [sys.executable, str(EXAMPLE)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "REFUSED" in result.stdout, (
        "The demonstration should include at least one REFUSED case."
    )


def test_example_accepts_valid_reference():
    """Running the demo must mention an ACCEPTED decision at least once."""
    result = subprocess.run(
        [sys.executable, str(EXAMPLE)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "ACCEPTED" in result.stdout, (
        "The demonstration should include at least one ACCEPTED case."
    )
