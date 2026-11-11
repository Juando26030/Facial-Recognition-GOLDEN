"""F5-9 E: qué secretos recibe cada servicio y el Job de operaciones (deploy/gcp/config.sh y deploy.sh), leído con bash y un `gcloud` falso (no toca la nube)."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="sin bash")


def _lists(tmp_path, env: str) -> dict:
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    g = fake / "gcloud"
    g.write_text("#!/bin/sh\necho 123\n", encoding="utf-8")
    g.chmod(0o755)
    script = ('set -e; export SPLIT_SERVICE_ACCOUNTS=1 REGION=us-east4 PROJECT_ID=p; source deploy/gcp/config.sh "$1" >/dev/null; '
              'echo "PUBLICO=$(service_secrets publico | tr "\\n" " ")"; echo "BIOMETRIA=$(service_secrets biometria | tr "\\n" " ")"; '
              'echo "WEB=$(service_secrets web | tr "\\n" " ")"; echo "OPS=$(echo $OPS_SECRETS | tr "\\n" " ")"')
    out = subprocess.run(["bash", "-c", script, "x", env], cwd=ROOT, capture_output=True, text=True, timeout=30,
                         env={**os.environ, "PATH": f"{fake}{os.pathsep}{os.environ.get('PATH', '')}"})
    assert out.returncode == 0, out.stderr
    res = {}
    for line in out.stdout.splitlines():
        k, _, v = line.partition("=")
        res[k] = {item.split(":")[0] for item in v.split()}
    return res


def test_public_and_biometric_services_get_only_what_they_use(tmp_path):
    s = _lists(tmp_path, "production")
    pub, bio, ops = s["PUBLICO"], s["BIOMETRIA"], s["OPS"]
    assert "payment-keys-encryption-key" in pub                 # /f/ y /webhooks/ descifran secretos de cuentas de cobro de terceros
    assert not {"wompi-private-key", "wompi-sandbox-private-key", "azure-client-secret", "graph-sender"} & pub
    assert not any(n.startswith(("wompi-", "azure-", "payment-", "onedrive-")) for n in bio)
    assert not any(n.startswith("onedrive-") or n == "backup-copy-encryption-key" for n in pub | bio | s["WEB"])
    assert {"onedrive-client-secret", "backup-copy-encryption-key"} <= ops


def test_staging_never_wires_production_only_secrets():
    src = (ROOT / "deploy" / "gcp" / "deploy.sh").read_text(encoding="utf-8")
    line = next(ln for ln in src.splitlines() if 'if [ "$GOLDEN_ENV" = staging ]; then case "$name" in' in ln)
    for pat in ("azure-*", "graph-sender", "wompi-public-key", "wompi-integrity-secret", "wompi-events-secret", "wompi-private-key", "onedrive-*", "backup-copy-encryption-key"):
        assert pat in line, pat
