"""Roles personalizados recién creados: asignarlos de inmediato falla un rato con «Role (...) does not exist in the resource's hierarchy» (propagación de IAM; producción, 9-oct-2026, paso 6).
deploy/gcp/lib_iam.sh reintenta SOLO ese error. Aquí no se toca la nube: un `gcloud` de mentira falla las primeras N veces y los comandos reales de bootstrap.sh se extraen y se ejecutan."""
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="sin bash")
ROOT = Path(__file__).resolve().parent.parent
PROPAGATION = "ERROR: (gcloud.storage.buckets.add-iam-policy-binding) HTTPError 400: Role (projects/goldenweb-prod/roles/goldenBackupLister) does not exist in the resource's hierarchy."

FAKE = r'''#!/usr/bin/env bash
n=$(cat "$FAKE_DIR/count" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$FAKE_DIR/count"
echo "CALL $*" >> "$FAKE_DIR/calls.log"
if [ "$n" -le "${FAKE_FAILS:-0}" ]; then echo "$FAKE_ERROR" >&2; exit 1; fi
echo "Updated IAM policy"
'''


def _run(tmp_path, body: str, fails: int = 0, error: str = PROPAGATION, tries: str = "6"):
    fake = tmp_path / "gcloud"
    fake.write_text(FAKE, encoding="utf-8", newline="\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    for f in ("count", "calls.log"):
        (tmp_path / f).unlink(missing_ok=True)
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}", "FAKE_DIR": str(tmp_path), "FAKE_FAILS": str(fails), "FAKE_ERROR": error,
           "IAM_RETRY_WAIT": "0", "IAM_RETRY_TRIES": tries}
    raw = subprocess.run([BASH, "-c", f"source deploy/gcp/lib_iam.sh\n{body}"], capture_output=True, env=env, cwd=ROOT)
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8").splitlines() if (tmp_path / "calls.log").exists() else []
    return raw.returncode, raw.stdout.decode("utf-8", "replace"), raw.stderr.decode("utf-8", "replace"), calls


def test_a_binding_that_works_the_first_time_is_not_retried_and_prints_nothing(tmp_path):
    rc, out, err, calls = _run(tmp_path, "retry_iam gcloud storage buckets add-iam-policy-binding gs://b --role x")
    assert rc == 0 and len(calls) == 1 and "esperando" not in err and out == ""


def test_the_propagation_error_is_retried_until_the_role_exists(tmp_path):
    rc, out, err, calls = _run(tmp_path, "retry_iam gcloud storage buckets add-iam-policy-binding gs://b --role projects/p/roles/goldenBackupLister", fails=3)
    assert rc == 0 and len(calls) == 4
    assert err.count("esperando que el rol se propague") == 3 and "intento 1 de 6" in err and "intento 3 de 6" in err


def test_after_six_attempts_it_fails_with_a_clear_message(tmp_path):
    rc, out, err, calls = _run(tmp_path, "retry_iam gcloud storage buckets add-iam-policy-binding gs://b --role projects/p/roles/goldenBackupLister", fails=99)
    assert rc == 1 and len(calls) == 6                                                   # exactamente 6 intentos
    assert err.count("esperando que el rol se propague") == 5
    assert "does not exist in the resource's hierarchy" in err and "tras 6 intentos" in err and "vuelve a correr el MISMO comando" in err


def test_any_other_error_fails_immediately_and_is_shown_as_is(tmp_path):
    denied = "ERROR: (gcloud.storage.buckets.add-iam-policy-binding) HTTPError 403: The caller does not have permission"
    rc, out, err, calls = _run(tmp_path, "retry_iam gcloud storage buckets add-iam-policy-binding gs://b --role roles/storage.objectAdmin", fails=99, error=denied)
    assert rc == 1 and len(calls) == 1 and "esperando" not in err and "does not have permission" in err


def _extract(name: str) -> str:
    """El texto REAL de la función `name` de bootstrap.sh (de una línea o de varias)."""
    lines = (ROOT / "deploy/gcp/bootstrap.sh").read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"{name}() {{"):
            if line.rstrip().endswith("}"):
                return line
            j = i
            while lines[j] != "}":
                j += 1
            return "\n".join(lines[i:j + 1])
    raise AssertionError(f"no está {name} en bootstrap.sh")


@pytest.mark.parametrize("fn,args", [
    ("bucket_bind", 'bucket_bind goldenweb-prod-golden-backups-us-east4 golden-ops "projects/goldenweb-prod/roles/goldenBackupLister"'),
    ("bucket_bind", 'bucket_bind goldenweb-prod-golden-backups-us-east4 golden-app "projects/goldenweb-prod/roles/goldenBackupLister"'),
    ("project_bind", 'project_bind golden-deployer "projects/goldenweb-prod/roles/goldenRunOperationsViewer"'),
    ("sa_bind", "sa_bind golden-app golden-deployer roles/iam.serviceAccountUser"),
    ("bind_job", 'bind_job golden-ops golden-invoker roles/run.invoker'),
    ("bind_svc", 'bind_svc golden-web golden-deployer roles/run.developer'),
])
def test_the_real_binding_functions_of_the_bootstrap_retry_the_propagation_error(tmp_path, fn, args):
    prelude = 'sa_email() { echo "$1@goldenweb-prod.iam.gserviceaccount.com"; }\nPROJECT_ID=goldenweb-prod; REGION=us-east4\n'
    rc, out, err, calls = _run(tmp_path, prelude + _extract(fn) + "\n" + args, fails=2)
    assert rc == 0, err
    assert len(calls) == 3 and err.count("esperando que el rol se propague") == 2         # 2 fallos de propagación y el tercero entra


def test_bootstrap_loads_the_library_and_no_binding_function_calls_gcloud_directly():
    b = (ROOT / "deploy/gcp/bootstrap.sh").read_text(encoding="utf-8")
    assert "source deploy/gcp/lib_iam.sh" in b
    for fn in ("sa_bind", "project_bind", "bucket_bind", "bind_job", "bind_svc"):
        body = _extract(fn)
        assert "retry_iam gcloud" in body and re.search(r"(?<!retry_iam )gcloud [a-z ]*add-iam-policy-binding", body) is None, fn
    # los dos roles personalizados que se crean y se usan en la misma corrida pasan por esas funciones
    assert 'project_bind "$SA_DEPLOYER" "projects/${PROJECT_ID}/roles/${OPS_ROLE}"' in b
    assert 'bucket_bind "$BACKUP_BUCKET" "$SA_OPS" "$LISTER"' in b and 'bucket_bind "$BACKUP_BUCKET" "$SA_APP" "$LISTER"' in b
    created = re.findall(r"gcloud iam roles create (\"?\$?\w+\"?)", b)
    assert sorted(c.strip('"') for c in created) == ["$OPS_ROLE", "goldenBackupLister", "goldenBackupReader", "goldenOffsiteState"]   # no hay otro rol personalizado sin cubrir
    # copia semanal: el lector pasa por bucket_bind (con reintentos); el de estado lleva condición IAM (bucket_bind no la maneja), espera la propagación al crearse y su enlace no detiene el bootstrap
    assert 'bucket_bind "$BACKUP_BUCKET" "$SA_OPS" "projects/${PROJECT_ID}/roles/goldenBackupReader"' in b
    assert "goldenOffsiteState --project \"$PROJECT_ID\"" in b and "sleep 45" in b
