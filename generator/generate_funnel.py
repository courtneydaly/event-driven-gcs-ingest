"""
Synthetic graduate-admissions funnel, exported the way a marketing automation
platform typically drops files on SFTP: one CSV per day containing every
applicant record that changed that day (a change-data-capture style export).

Fictional university, programs, and people. Invariants (tested):
  * stages are nested: admitted => submitted => started => inquired
  * stage dates never go backwards
  * every applicant's latest record carries their furthest stage

  python generator/generate_funnel.py --out data/sftp_drop
"""
from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

STAGES = ["inquiry", "app_started", "app_submitted", "admitted", "deposited"]
# conditional probability of reaching each stage from the previous one
ADVANCE = {"app_started": 0.42, "app_submitted": 0.61, "admitted": 0.68, "deposited": 0.47}
# median days between stages
LAG = {"app_started": 9, "app_submitted": 16, "admitted": 21, "deposited": 12}

PROGRAMS = {
    "MS Data Analytics": 1.0, "MBA (Online)": 1.4, "Master of Public Health": 0.8,
    "MEd Instructional Design": 0.6, "MS Cybersecurity": 0.9,
}
CHANNELS = {"paid_search": 0.30, "paid_social": 0.22, "organic": 0.20, "email": 0.12, "referral": 0.09, "event": 0.07}
# channel quality: multiplier on every advance probability
CHANNEL_QUALITY = {"paid_search": 1.05, "paid_social": 0.80, "organic": 1.10, "email": 1.15, "referral": 1.25, "event": 1.0}

FIELDS = ["applicant_id", "program", "term", "source_channel", "current_stage"] + \
         [f"{s}_date" for s in STAGES] + ["record_updated_at"]


def simulate(start: date, end: date, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    people = []
    n_days = (end - start).days + 1
    pid = 100000
    for day in range(n_days):
        d = start + timedelta(days=day)
        n_inquiries = max(0, int(rng.gauss(38 if d.weekday() < 5 else 22, 6)))
        for _ in range(n_inquiries):
            pid += 1
            program = rng.choices(list(PROGRAMS), weights=list(PROGRAMS.values()))[0]
            channel = rng.choices(list(CHANNELS), weights=list(CHANNELS.values()))[0]
            dates = {"inquiry": d}
            prev = d
            for stage in STAGES[1:]:
                if rng.random() > min(0.95, ADVANCE[stage] * CHANNEL_QUALITY[channel]):
                    break
                prev = prev + timedelta(days=max(1, int(rng.expovariate(1 / LAG[stage]))))
                if prev > end:
                    break
                dates[stage] = prev
            people.append({
                "applicant_id": f"A{pid}", "program": program,
                "term": "Fall 2026" if d < date(2026, 6, 1) else "Spring 2027",
                "source_channel": channel, "dates": dates,
            })
    return people


def daily_exports(people: list[dict]) -> dict[date, list[dict]]:
    """Each day's file holds the current state of every record that changed that day."""
    files: dict[date, list[dict]] = {}
    for p in people:
        reached = []
        for stage in STAGES:
            if stage not in p["dates"]:
                break
            reached.append(stage)
            d = p["dates"][stage]
            row = {
                "applicant_id": p["applicant_id"], "program": p["program"], "term": p["term"],
                "source_channel": p["source_channel"], "current_stage": stage,
                **{f"{s}_date": (p["dates"][s].isoformat() if s in reached else "") for s in STAGES},
                "record_updated_at": f"{d.isoformat()}T{2 + len(reached):02d}:15:00Z",
            }
            files.setdefault(d, []).append(row)
    return files


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-05")
    ap.add_argument("--end", default="2026-09-30")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="data/sftp_drop")
    args = ap.parse_args()
    files = daily_exports(simulate(date.fromisoformat(args.start), date.fromisoformat(args.end), args.seed))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for d, rows in sorted(files.items()):
        with open(out / f"applicants_{d:%Y%m%d}.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
    print(f"wrote {len(files)} daily files, {sum(len(r) for r in files.values()):,} records -> {out}")


if __name__ == "__main__":
    main()
