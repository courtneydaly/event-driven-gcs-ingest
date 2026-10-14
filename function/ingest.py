"""
Pure transfer logic (no GCP or network imports), so it can be unit tested.

Idempotency: the GCS object path is derived only from the file name, and a
file whose object already exists with the same size is skipped. Re-running the
job, or two overlapping runs, never double-loads a file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

FILE_RE = re.compile(r"^(?P<prefix>[a-z_]+)_(?P<ymd>\d{8})\.csv$")


@dataclass(frozen=True)
class RemoteFile:
    name: str
    size: int


def blob_path(filename: str, root: str = "raw") -> str:
    """applicants_20260314.csv -> raw/applicants/dt=2026-03-14/applicants_20260314.csv"""
    m = FILE_RE.match(filename)
    if not m:
        raise ValueError(f"unexpected file name: {filename}")
    d: date = datetime.strptime(m["ymd"], "%Y%m%d").date()
    return f"{root}/{m['prefix']}/dt={d.isoformat()}/{filename}"


def plan_transfers(remote: list[RemoteFile], existing: dict[str, int], root: str = "raw") -> dict:
    """
    remote:   files on the SFTP server
    existing: {blob_path: size} already in GCS
    -> {"copy": [...], "skip": [...], "ignored": [...], "size_mismatch": [...]}
    """
    plan = {"copy": [], "skip": [], "ignored": [], "size_mismatch": []}
    for f in sorted(remote, key=lambda f: f.name):
        if not FILE_RE.match(f.name):
            plan["ignored"].append(f.name)
            continue
        path = blob_path(f.name, root)
        if path not in existing:
            plan["copy"].append((f, path))
        elif existing[path] == f.size:
            plan["skip"].append(f.name)
        else:
            # Same name, different size: the upstream re-sent a corrected file.
            # Don't silently overwrite history; flag it for a human.
            plan["size_mismatch"].append(f.name)
    return plan
