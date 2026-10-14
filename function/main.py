"""
Cloud Run function: copy new export files from SFTP into Cloud Storage.
Triggered on a schedule by Cloud Scheduler (HTTP, OIDC-authenticated).

Env:
  SFTP_HOST, SFTP_USER, SFTP_DIR      connection settings
  SFTP_KEY_SECRET                     Secret Manager resource name of the private key
  SFTP_HOST_KEY                       expected host public key ("ssh-ed25519 AAAA...")
  GCS_BUCKET                          landing bucket
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os

import functions_framework
import paramiko
from google.cloud import secretmanager, storage

from ingest import RemoteFile, plan_transfers

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sftp-ingest")


def _sftp() -> tuple[paramiko.SSHClient, paramiko.SFTPClient]:
    key_pem = secretmanager.SecretManagerServiceClient().access_secret_version(
        name=os.environ["SFTP_KEY_SECRET"]).payload.data.decode()
    pkey = paramiko.Ed25519Key.from_private_key(io.StringIO(key_pem))
    ssh = paramiko.SSHClient()
    # Pin the server's host key. Never AutoAddPolicy in production.
    host = os.environ["SFTP_HOST"]
    ktype, kdata = os.environ["SFTP_HOST_KEY"].split()[:2]
    ssh.get_host_keys().add(host, ktype, paramiko.PKey.from_type_string(ktype, base64.b64decode(kdata)))
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(host, username=os.environ["SFTP_USER"], pkey=pkey, timeout=30)
    return ssh, ssh.open_sftp()


@functions_framework.http
def ingest(request):
    bucket = storage.Client().bucket(os.environ["GCS_BUCKET"])
    ssh, sftp = _sftp()
    try:
        remote_dir = os.environ.get("SFTP_DIR", ".")
        remote = [RemoteFile(a.filename, a.st_size) for a in sftp.listdir_attr(remote_dir)]
        existing = {b.name: b.size for b in bucket.list_blobs(prefix="raw/")}
        plan = plan_transfers(remote, existing)

        copied = []
        for f, path in plan["copy"]:
            blob = bucket.blob(path)
            with sftp.open(f"{remote_dir}/{f.name}", "rb") as src:
                src.prefetch()
                # if_generation_match=0: only create, never overwrite, even if two runs race.
                blob.upload_from_file(src, size=f.size, content_type="text/csv", if_generation_match=0)
            copied.append(path)
            log.info("copied %s -> gs://%s/%s", f.name, bucket.name, path)

        if plan["size_mismatch"]:
            log.warning("size mismatch, not overwritten: %s", plan["size_mismatch"])
        summary = {"copied": copied, "skipped": len(plan["skip"]),
                   "ignored": plan["ignored"], "size_mismatch": plan["size_mismatch"]}
        return json.dumps(summary), 200, {"Content-Type": "application/json"}
    finally:
        sftp.close()
        ssh.close()
