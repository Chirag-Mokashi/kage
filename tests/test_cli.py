"""End-to-end tests for the kage CLI.

Black-box: each test runs the real `kage` command in a subprocess with an
isolated KAGE_HOME (a temp dir), so the user's real ~/.kage is never touched.
Covers the smoke path + the two invariants that guard correctness:
the save-wall (#16) and the project partition wall (#99).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest


def run(args, home, stdin=None):
    """Invoke the kage CLI in a subprocess with an isolated KAGE_HOME."""
    env = {**os.environ, "KAGE_HOME": str(home)}
    return subprocess.run(
        [sys.executable, "-m", "kage.cli", *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
    )


def _id_from(stdout: str) -> str:
    m = re.search(r"\[([0-9T]+-[0-9a-f]+)\]", stdout)
    assert m, f"no memory id found in output:\n{stdout}"
    return m.group(1)


@pytest.fixture
def home(tmp_path):
    """A fresh, initialized, isolated kage store."""
    h = tmp_path / ".kage"
    assert run(["init"], h).returncode == 0
    return h


# ── smoke ──────────────────────────────────────────────────────────────────

def test_init_creates_store(tmp_path):
    h = tmp_path / ".kage"
    res = run(["init"], h)
    assert res.returncode == 0
    assert (h / "memory").is_dir()
    assert (h / "indexes" / "kage.db").is_file()
    assert (h / "config.json").is_file()


def test_remember_recall_roundtrip(home):
    r = run(["remember", "the eiffel tower is in paris", "-p", "trivia", "-y"], home)
    assert r.returncode == 0 and "saved" in r.stdout

    found = run(["recall", "eiffel"], home)
    assert found.returncode == 0
    assert "paris" in found.stdout.lower()


# ── invariants (must always hold) ───────────────────────────────────────────

def test_wall_blocks_unconfirmed_save(home):
    # Decline the confirm prompt -> nothing may persist (the wall, #16).
    r = run(["remember", "secret note", "-p", "x"], home, stdin="n\n")
    assert "Discarded" in r.stdout
    assert "No matches" in run(["recall", "secret"], home).stdout


def test_partition_wall_isolates_projects(home):
    run(["remember", "alpha shared word", "-p", "projA", "-y"], home)
    run(["remember", "beta shared word", "-p", "projB", "-y"], home)

    a = run(["recall", "shared", "-p", "projA"], home).stdout
    assert "alpha" in a and "beta" not in a  # projA query must not leak projB

    b = run(["recall", "shared", "-p", "projB"], home).stdout
    assert "beta" in b and "alpha" not in b


# ── forget + doctor ──────────────────────────────────────────────────────────

def test_forget_removes_note(home):
    saved = run(["remember", "delete me please", "-p", "tmp", "-y"], home)
    mem_id = _id_from(saved.stdout)

    f = run(["forget", mem_id, "-y"], home)
    assert f.returncode == 0 and "forgotten" in f.stdout
    assert "No matches" in run(["recall", "delete"], home).stdout


def test_doctor_healthy(home):
    r = run(["doctor"], home)
    assert r.returncode == 0 and "healthy" in r.stdout


def test_doctor_detects_drift(home):
    run(["remember", "a note", "-p", "p", "-y"], home)
    # Delete the markdown file behind kage's back -> index now disagrees.
    next((home / "memory").glob("*.md")).unlink()

    r = run(["doctor"], home)
    assert r.returncode == 1          # unhealthy
    assert "consistent" in r.stdout   # the consistency check is the one that fails
