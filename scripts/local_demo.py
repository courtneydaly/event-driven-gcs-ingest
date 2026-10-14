"""
Run the transfer logic locally: a folder stands in for the SFTP server and another
for the GCS bucket. Run it twice to see idempotency.

  python generator/generate_funnel.py --out data/sftp_drop
  python scripts/local_demo.py
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "function"))
from ingest import RemoteFile, plan_transfers  # noqa: E402

src, bucket = ROOT / "data/sftp_drop", ROOT / "data/fake_bucket"
remote = [RemoteFile(p.name, p.stat().st_size) for p in src.iterdir()]
existing = {str(p.relative_to(bucket)): p.stat().st_size for p in bucket.rglob("*.csv")} if bucket.exists() else {}
plan = plan_transfers(remote, existing)
for f, path in plan["copy"]:
    (bucket / path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src / f.name, bucket / path)
print(f"copied {len(plan['copy'])}, skipped {len(plan['skip'])}, "
      f"ignored {len(plan['ignored'])}, size mismatches {len(plan['size_mismatch'])}")
