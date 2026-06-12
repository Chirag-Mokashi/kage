"""Retrieval eval harness — Cycle 8.

Measures recall@k and MRR across 20 cases covering short-fact recall,
buried facts in headerless notes, keyword collisions, semantic-only
matches, multi-section notes, and project partition walls.

Run:  uv run pytest tests/eval_retrieval.py -v -s
      (requires: uv sync; Ollama optional — FTS-only without it)

This file DOES NOT assert pass/fail thresholds. It prints a results table
and always exits 0. Data sets the bar; thresholds come after Cycle 8 ships.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

import pytest
from typer.testing import CliRunner

from kage import cli

CORPUS_DIR = Path(__file__).parent / "fixtures" / "eval_corpus"

FIXTURE_PROJECTS: dict[str, str] = {
    "01-kage-privacy-gate":    "kage",
    "02-kage-roadmap":         "kage",
    "03-neu-advisor":          "school",
    "04-neu-thesis-topic":     "school",
    "05-neu-course-deadlines": "school",
    "06-coffee-preference":    "personal",
    "07-apollo-project":       "kage",
    "08-apollo-cafe":          "personal",
    "09-budget-ai-cloud":      "finance",
    "10-budget-goa-trip":      "personal",
    "11-gym-routine":          "health",
    "12-sleep-notes":          "health",
    "13-mom-birthday":         "personal",
    "14-kage-jugaad":          "kage",
    "15-recipe-dal":           "recipes",
    "16-laptop-specs":         "personal",
    "17-meeting-notes-2026-05": "school",
    "18-perplexity-vs-cosmos": "kage",
}


class EvalCase(NamedTuple):
    query: str
    expected: list[str]
    project: str | None
    category: str


EVAL_CASES: list[EvalCase] = [
    # short-fact recall — should mostly pass at baseline
    EvalCase("what time are my advisor's office hours?",          ["03-neu-advisor"],           None,      "short-fact"),
    EvalCase("when is the ML systems project due?",               ["05-neu-course-deadlines"],  None,      "short-fact"),
    EvalCase("how do I take my coffee?",                          ["06-coffee-preference"],     None,      "short-fact"),
    EvalCase("how much sleep should I be getting?",               ["12-sleep-notes"],           None,      "short-fact"),
    EvalCase("when is mom's birthday and what flowers does she like?", ["13-mom-birthday"],     None,      "short-fact"),
    EvalCase("what laptop do I use?",                             ["16-laptop-specs"],          None,      "short-fact"),
    # buried fact in headerless prose — exercises chunking bug
    EvalCase("what is my thesis actually about?",                 ["04-neu-thesis-topic"],      None,      "buried-fact"),
    EvalCase("which day is my full rest day?",                    ["11-gym-routine"],           None,      "buried-fact"),
    EvalCase("what did we decide about the showcase demo?",       ["17-meeting-notes-2026-05"], None,      "buried-fact"),
    # keyword collisions — reranker should promote the right one
    EvalCase("which Apollo is the export feature?",               ["07-apollo-project"],        None,      "collision"),
    EvalCase("where's a good cold brew near campus?",             ["08-apollo-cafe"],           None,      "collision"),
    EvalCase("what's my monthly cap for cloud AI spend?",         ["09-budget-ai-cloud"],       None,      "collision"),
    EvalCase("how much is the Goa trip going to cost?",           ["10-budget-goa-trip"],       None,      "collision"),
    # semantic match — note never uses the query's words
    EvalCase("how does kage avoid spending money?",               ["14-kage-jugaad"],           None,      "semantic"),
    EvalCase("does Perplexity's API cost extra beyond the subscription?", ["18-perplexity-vs-cosmos"], None, "semantic"),
    # multi-section notes
    EvalCase("what does the privacy gate check before sending?",  ["01-kage-privacy-gate"],     None,      "multi-section"),
    EvalCase("what's planned for cycle 9?",                       ["02-kage-roadmap"],          None,      "multi-section"),
    EvalCase("what are the steps to make dal?",                   ["15-recipe-dal"],            None,      "multi-section"),
    # project partition wall — scoped query must not leak
    EvalCase("budget",  ["09-budget-ai-cloud"],  "finance", "partition"),
    EvalCase("Apollo",  ["07-apollo-project"],   "kage",    "partition"),
]

LIMIT = 20  # retrieve this many; measure recall at k=1,3,5,10,20


@pytest.fixture
def eval_store(tmp_path, monkeypatch):
    """Isolated kage store with all 18 fixture notes loaded. Returns slug→note_id map."""
    h = tmp_path / ".kage"
    for attr, val in {
        "KAGE_HOME":   h,
        "MEMORY_DIR":  h / "memory",
        "INDEX_DIR":   h / "indexes",
        "DB_PATH":     h / "indexes" / "kage.db",
        "CONFIG_PATH": h / "config.json",
        "CHROMA_DIR":  h / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)

    CliRunner().invoke(cli.app, ["init"])

    slug_to_id: dict[str, str] = {}
    for md_path in sorted(CORPUS_DIR.glob("*.md")):
        slug = md_path.stem
        project = FIXTURE_PROJECTS[slug]
        text = md_path.read_text()
        note_id = cli._save(text, project, embed=True)
        slug_to_id[slug] = note_id

    return slug_to_id


def _rank_of(note_id: str, rows: list) -> int | None:
    """1-based rank of note_id in rows; None if not present."""
    for i, row in enumerate(rows, 1):
        if row[0] == note_id:
            return i
    return None


def _run_cases(slug_to_id: dict[str, str]) -> list[dict]:
    results = []
    for case in EVAL_CASES:
        rows = cli._search(case.query, case.project, LIMIT, any_terms=True)
        result_ids = [row[0] for row in rows]

        expected_ids = [slug_to_id[s] for s in case.expected if s in slug_to_id]
        best_rank: int | None = None
        for eid in expected_ids:
            r = _rank_of(eid, rows)
            if r is not None and (best_rank is None or r < best_rank):
                best_rank = r

        results.append({
            "query":    case.query[:55],
            "category": case.category,
            "project":  case.project,
            "rank":     best_rank,
            "hits_20":  best_rank is not None,
        })
    return results


def _print_report(results: list[dict], mode: str) -> None:
    n = len(results)
    print(f"\n{'─'*70}")
    print(f"  Retrieval eval — kage Cycle 8 baseline   mode={mode}   n={n}")
    print(f"{'─'*70}")
    print(f"  {'Query':<56} {'Cat':<12} {'Rank':>5}")
    print(f"  {'─'*56} {'─'*12} {'─'*5}")
    for r in results:
        scope = f"[{r['project']}]" if r["project"] else ""
        rank_str = str(r["rank"]) if r["rank"] is not None else "—"
        print(f"  {r['query']:<56} {r['category']:<12} {rank_str:>5}  {scope}")

    print(f"\n  Recall@k:")
    for k in [1, 3, 5, 10, 20]:
        hits = sum(1 for r in results if r["rank"] is not None and r["rank"] <= k)
        print(f"    @{k:<3}  {hits}/{n}  ({100*hits/n:.0f}%)")

    mrr = sum(1.0 / r["rank"] for r in results if r["rank"] is not None) / n
    print(f"\n  MRR (limit={LIMIT}): {mrr:.3f}")

    by_cat: dict[str, list] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)
    print(f"\n  By category (recall@5):")
    for cat, rows in sorted(by_cat.items()):
        hits5 = sum(1 for r in rows if r["rank"] is not None and r["rank"] <= 5)
        print(f"    {cat:<14} {hits5}/{len(rows)}")
    print(f"{'─'*70}\n")


def test_eval_retrieval_baseline(eval_store, capsys):
    """Run 20 eval cases against today's retriever and print recall@k / MRR table.

    Always passes — this is measurement, not a threshold check.
    Run with: uv run pytest tests/eval_retrieval.py -v -s
    """
    slug_to_id = eval_store

    ollama_up = True
    try:
        cli._embed("ping")
    except cli.OllamaUnavailable:
        ollama_up = False

    mode = "hybrid (FTS+vec)" if ollama_up else "FTS-only"
    if not ollama_up:
        print(
            "\n  [eval] Ollama unavailable — running FTS-only baseline.\n"
            "  Start Ollama + nomic-embed-text for hybrid results.",
            file=sys.stderr,
        )

    results = _run_cases(slug_to_id)

    with capsys.disabled():
        _print_report(results, mode)


# ── Identity wall eval (Cycle 9) ─────────────────────────────────────────────

@pytest.fixture
def wall_store(tmp_path, monkeypatch):
    """Isolated store with one personal note and one NEU note — for wall-invariant testing."""
    h = tmp_path / ".kage"
    for attr, val in {
        "KAGE_HOME":   h,
        "MEMORY_DIR":  h / "memory",
        "INDEX_DIR":   h / "indexes",
        "DB_PATH":     h / "indexes" / "kage.db",
        "CONFIG_PATH": h / "config.json",
        "CHROMA_DIR":  h / "chroma",
    }.items():
        monkeypatch.setattr(cli, attr, val)

    CliRunner().invoke(cli.app, ["init"])

    monkeypatch.setattr(cli, "_embed", lambda *a, **kw: (_ for _ in ()).throw(cli.OllamaUnavailable("down")))

    class FakeChroma:
        def add(self, **kw): pass
        def count(self): return 0
        def get(self, **kw): return {"ids": []}
        def query(self, **kw): return {"ids": [[]], "metadatas": [[]], "distances": [[]]}

    monkeypatch.setattr(cli, "_get_chroma", lambda: FakeChroma())

    personal_id = cli._save(
        "kage is my personal memory broker. okiro triggers the system.",
        "kage",
        identities=["personal"],
    )
    neu_id = cli._save(
        "glioblastoma tumor detection using hyperspectral imaging. HybridSN ViT.",
        "hsi",
        identities=["neu"],
    )
    return {"personal": personal_id, "neu": neu_id}


def test_eval_identity_wall(wall_store, capsys):
    """Wall invariant: no cross-identity leakage in either direction.

    personal identity never returns NEU notes; NEU identity never returns personal notes.
    Both identities CAN find their own notes (proves the wall is not over-blocking).
    """
    personal_id = wall_store["personal"]
    neu_id = wall_store["neu"]

    rows = cli._search("glioblastoma tumor detection", None, 10, any_terms=True, identity="personal")
    p1 = neu_id not in [r[0] for r in rows]

    rows = cli._search("kage memory broker okiro", None, 10, any_terms=True, identity="neu")
    p2 = personal_id not in [r[0] for r in rows]

    rows = cli._search("glioblastoma tumor detection", None, 10, any_terms=True, identity="neu")
    p3 = neu_id in [r[0] for r in rows]

    rows = cli._search("kage memory broker okiro", None, 10, any_terms=True, identity="personal")
    p4 = personal_id in [r[0] for r in rows]

    with capsys.disabled():
        print("\n  Identity wall invariants (Cycle 9):")
        print(f"    personal→NEU blocked:      {'PASS' if p1 else 'FAIL'}")
        print(f"    NEU→personal blocked:      {'PASS' if p2 else 'FAIL'}")
        print(f"    NEU finds own notes:       {'PASS' if p3 else 'FAIL'}")
        print(f"    personal finds own notes:  {'PASS' if p4 else 'FAIL'}")

    assert p1, "NEU note leaked into personal identity search"
    assert p2, "Personal note leaked into NEU identity search"
    assert p3, "NEU note not found with correct NEU identity"
    assert p4, "Personal note not found with correct personal identity"
