import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "function"))
sys.path.insert(0, str(ROOT / "generator"))

import generate_funnel as g  # noqa: E402
from ingest import RemoteFile, blob_path, plan_transfers  # noqa: E402

PEOPLE = g.simulate(date(2026, 1, 5), date(2026, 4, 30), seed=3)
FILES = g.daily_exports(PEOPLE)


def test_blob_path_is_date_partitioned():
    assert blob_path("applicants_20260314.csv") == "raw/applicants/dt=2026-03-14/applicants_20260314.csv"
    with pytest.raises(ValueError):
        blob_path("applicants_latest.csv")


def test_plan_is_idempotent():
    remote = [RemoteFile("applicants_20260314.csv", 100), RemoteFile("applicants_20260315.csv", 120)]
    first = plan_transfers(remote, {})
    assert len(first["copy"]) == 2
    existing = {path: f.size for f, path in first["copy"]}
    second = plan_transfers(remote, existing)
    assert second["copy"] == [] and len(second["skip"]) == 2


def test_resent_file_with_new_size_is_flagged_not_overwritten():
    remote = [RemoteFile("applicants_20260314.csv", 150)]
    plan = plan_transfers(remote, {"raw/applicants/dt=2026-03-14/applicants_20260314.csv": 100})
    assert plan["size_mismatch"] == ["applicants_20260314.csv"] and plan["copy"] == []


def test_unexpected_files_are_ignored():
    plan = plan_transfers([RemoteFile("README.txt", 5), RemoteFile(".DS_Store", 1)], {})
    assert plan["ignored"] == [".DS_Store", "README.txt"]


def test_funnel_stages_are_nested_and_ordered():
    for p in PEOPLE:
        reached = [s for s in g.STAGES if s in p["dates"]]
        assert reached == g.STAGES[: len(reached)]           # no skipped stages
        ds = [p["dates"][s] for s in reached]
        assert ds == sorted(ds)                               # dates never go backwards


def test_latest_record_carries_furthest_stage():
    latest = {}
    for rows in FILES.values():
        for r in rows:
            if r["applicant_id"] not in latest or r["record_updated_at"] > latest[r["applicant_id"]]["record_updated_at"]:
                latest[r["applicant_id"]] = r
    for p in PEOPLE:
        furthest = [s for s in g.STAGES if s in p["dates"]][-1]
        assert latest[p["applicant_id"]]["current_stage"] == furthest


def test_cohort_funnel_is_monotonic():
    counts = [sum(1 for p in PEOPLE if s in p["dates"]) for s in g.STAGES]
    assert counts == sorted(counts, reverse=True)
    # rates land in a plausible range for graduate admissions
    assert 0.03 < counts[-1] / counts[0] < 0.15
