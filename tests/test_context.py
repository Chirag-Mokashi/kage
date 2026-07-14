"""Tests for kage.context (Cycle 31 Slice 3) -- the rich per-axis resolver,
the .kage marker walk-up, and the frozen-resolver guarantee (the old
_resolve_context must never infer, even with the new gate enabled)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kage import context, runtime
from kage.config import Config


@pytest.fixture
def ctx_env(monkeypatch, tmp_path):
    """Isolated kage home; runtime.config points at it."""
    kage_home = tmp_path / ".kage"
    kage_home.mkdir()
    monkeypatch.setattr(runtime, "config", Config(kage_home))
    return kage_home


def _set_project_inference(kage_home, enabled: bool) -> None:
    (kage_home / "config.json").write_text(json.dumps({"project_inference": enabled}))


def _write_state(kage_home, **kwargs) -> None:
    (kage_home / "state.json").write_text(json.dumps(kwargs))


# -- _find_kage_marker_project --------------------------------------------

def test_marker_found_in_start_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".kage").write_text("project=widget\n")
    assert context._find_kage_marker_project(tmp_path) == "widget"


def test_marker_found_via_walk_up(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".kage").write_text("project=widget\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert context._find_kage_marker_project(nested) == "widget"


def test_marker_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert context._find_kage_marker_project(tmp_path) is None


def test_marker_without_project_line_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".kage").write_text("owner=chirag\n")
    assert context._find_kage_marker_project(tmp_path) is None


def test_marker_walk_up_stops_at_home(tmp_path, monkeypatch):
    (tmp_path / ".kage").write_text("project=above-home\n")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    nested = home / "a"
    nested.mkdir()
    assert context._find_kage_marker_project(nested) is None


# -- _resolve_context_rich -- identity axis (declared-only) ----------------

def test_rich_identity_declared_via_flag(ctx_env):
    res = context._resolve_context_rich("neu", None)
    assert res.identity.value == "neu"
    assert res.identity.confidence == "declared"
    assert res.identity.provenance == "flag"


def test_rich_identity_declared_via_sticky(ctx_env):
    _write_state(ctx_env, identity="neu")
    res = context._resolve_context_rich(None, None)
    assert res.identity.value == "neu"
    assert res.identity.confidence == "declared"
    assert res.identity.provenance == "sticky"


def test_rich_identity_fallback(ctx_env):
    res = context._resolve_context_rich(None, None)
    assert res.identity.value == "personal"
    assert res.identity.confidence == "fallback"


def test_rich_identity_never_inferred_from_marker(ctx_env, tmp_path, monkeypatch):
    _set_project_inference(ctx_env, True)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(Path, "home", lambda: work)
    monkeypatch.setattr(Path, "cwd", lambda: work)
    (work / ".kage").write_text("project=widget\n")
    res = context._resolve_context_rich(None, None)
    assert res.identity.confidence == "fallback"
    assert res.identity.value == "personal"


# -- _resolve_context_rich -- project axis (inferable) --------------------

def test_rich_project_declared_via_flag(ctx_env):
    res = context._resolve_context_rich(None, "hsi")
    assert res.project.value == "hsi"
    assert res.project.confidence == "declared"
    assert res.project.provenance == "flag"


def test_rich_project_marker_ignored_when_gate_off(ctx_env, tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(Path, "home", lambda: work)
    monkeypatch.setattr(Path, "cwd", lambda: work)
    (work / ".kage").write_text("project=widget\n")
    res = context._resolve_context_rich(None, None)
    assert res.project.provenance != "kage-marker"
    assert res.project.confidence == "fallback"


def test_rich_project_inferred_from_marker_when_gate_on(ctx_env, tmp_path, monkeypatch):
    _set_project_inference(ctx_env, True)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(Path, "home", lambda: work)
    monkeypatch.setattr(Path, "cwd", lambda: work)
    (work / ".kage").write_text("project=widget\n")
    res = context._resolve_context_rich(None, None)
    assert res.project.value == "widget"
    assert res.project.confidence == "inferred"
    assert res.project.provenance == "kage-marker"


def test_rich_project_marker_outranks_sticky(ctx_env, tmp_path, monkeypatch):
    _set_project_inference(ctx_env, True)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(Path, "home", lambda: work)
    monkeypatch.setattr(Path, "cwd", lambda: work)
    (work / ".kage").write_text("project=widget\n")
    _write_state(ctx_env, identity="neu", project="sticky-project")
    res = context._resolve_context_rich(None, None)
    assert res.project.value == "widget"
    assert res.project.provenance == "kage-marker"


def test_rich_project_sticky_when_no_marker(ctx_env):
    _write_state(ctx_env, identity="neu", project="sticky-project")
    res = context._resolve_context_rich(None, None)
    assert res.project.value == "sticky-project"
    assert res.project.confidence == "declared"
    assert res.project.provenance == "sticky"


def test_rich_project_explicit_wins_over_marker(ctx_env, tmp_path, monkeypatch):
    _set_project_inference(ctx_env, True)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(Path, "home", lambda: work)
    monkeypatch.setattr(Path, "cwd", lambda: work)
    (work / ".kage").write_text("project=widget\n")
    res = context._resolve_context_rich(None, "explicit-project")
    assert res.project.value == "explicit-project"
    assert res.project.provenance == "flag"


# -- frozen guarantee: the OLD resolver never infers -----------------------

def test_frozen_resolver_never_infers_even_when_marker_present_and_gate_on(
    ctx_env, tmp_path, monkeypatch
):
    _set_project_inference(ctx_env, True)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(Path, "home", lambda: work)
    monkeypatch.setattr(Path, "cwd", lambda: work)
    (work / ".kage").write_text("project=widget\n")
    identity, project, source = context._resolve_context(None, None)
    assert identity == "personal"
    assert project is None
    assert source == "fallback"
