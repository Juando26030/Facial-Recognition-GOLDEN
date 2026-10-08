"""CORS del bucket de la subida directa: las dos URL de Cloud Run del servicio web entran en staging, producción no lleva run.app (salvo CORS_INCLUDE_RUN_URLS=1), cors.sh es idempotente y bootstrap lo corre al final."""
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="sin bash")
ROOT = Path(__file__).resolve().parent.parent
HASH_URL = "https://golden-web-staging-rnvuhvw37q-uk.a.run.app"
FAKE = r'''#!/usr/bin/env bash
case "$*" in
  "config get-value project") echo proj ;;
  "projects describe"*) echo 123456 ;;
  "run services describe"*) printf '{"metadata":{"annotations":{"run.googleapis.com/urls":"[\\"HASH\\",\\"https://golden-web-staging-123456.us-east4.run.app\\"]"}}}' ;;
  "storage buckets describe"*) cat "$FAKE_BUCKET" ;;
  "storage buckets update"*) echo "$*" >> "$FAKE_LOG"; cp "${@: -2:1}" "$FAKE_APPLIED" 2>/dev/null || true
    for a in "$@"; do case "$prev" in --cors-file) cp "$a" "$FAKE_APPLIED" ;; esac; prev="$a"; done ;;
esac
'''.replace("HASH", HASH_URL)


def _run(tmp_path, args, bucket_cors, extra_env=None, script=None):
    fake = tmp_path / "gcloud"
    fake.write_text(FAKE, encoding="utf-8", newline="\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "bucket.json").write_text(json.dumps({"cors_config": bucket_cors}), encoding="utf-8")
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}", "REGION": "us-east4", "FAKE_BUCKET": str(tmp_path / "bucket.json"),
           "FAKE_LOG": str(tmp_path / "log.txt"), "FAKE_APPLIED": str(tmp_path / "applied.json"), "FIREBASE_SITE": "", **(extra_env or {})}
    env.pop("PUBLIC_BASE_URL", None)
    return subprocess.run([BASH, *args], capture_output=True, text=True, env=env, cwd=ROOT)


def _origins(tmp_path, env, extra_env=None):
    r = _run(tmp_path, ["-c", f"source deploy/gcp/config.sh {env}; cors_origins"], [], extra_env)
    assert r.returncode == 0, r.stderr
    return r.stdout.split()


def test_staging_has_both_cloud_run_url_formats(tmp_path):
    o = _origins(tmp_path, "staging")
    assert HASH_URL in o and "https://golden-web-staging-123456.us-east4.run.app" in o


def test_production_has_no_run_app_unless_asked(tmp_path):
    prod = {"PUBLIC_BASE_URL": "https://app.golden-eventos.com", "FIREBASE_SITE": "golden-prod"}
    o = _origins(tmp_path, "production", prod)
    assert "https://app.golden-eventos.com" in o and not any(".run.app" in x for x in o)
    o = _origins(tmp_path, "production", {**prod, "CORS_INCLUDE_RUN_URLS": "1"})
    assert any(x.endswith(".run.app") for x in o) and "https://app.golden-eventos.com" in o


def test_cors_sh_applies_the_exact_rule_and_is_idempotent(tmp_path):
    r = _run(tmp_path, ["deploy/gcp/cors.sh", "staging"], [])
    assert r.returncode == 0, r.stderr
    applied = json.loads((tmp_path / "applied.json").read_text(encoding="utf-8"))
    assert applied[0]["method"] == ["PUT"] and set(applied[0]["responseHeader"]) == {"Content-Type", "x-goog-content-length-range"}
    assert HASH_URL in applied[0]["origin"] and "https://golden-web-staging-123456.us-east4.run.app" in applied[0]["origin"]
    (tmp_path / "log.txt").unlink()
    again = _run(tmp_path, ["deploy/gcp/cors.sh", "staging"], applied)               # el bucket ya lo tiene: no se vuelve a escribir
    assert again.returncode == 0 and "aplicado" not in again.stdout and not (tmp_path / "log.txt").exists()


def test_bootstrap_applies_cors_again_after_the_services_exist():
    b = (ROOT / "deploy/gcp/bootstrap.sh").read_text(encoding="utf-8")
    assert b.index('bash deploy/gcp/cors.sh "$GOLDEN_ENV"') > b.index('step "8. Cloud Run')
