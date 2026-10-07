"""deploy.sh ya no se traga los errores al buscar la cola facial: «existe», «falta» o «error» (p. ej. la cuenta de despliegue sin permiso de lectura), y el error DETIENE el despliegue."""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="sin bash")


def _state(tmp_path, exit_code, stderr):
    fake = tmp_path / "gcloud"
    fake.write_text(f'#!/usr/bin/env bash\necho "{stderr}" >&2\n{"echo projects/p/locations/r/queues/golden-faces-staging" if exit_code == 0 else ""}\nexit {exit_code}\n', encoding="utf-8", newline="\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}", "QUEUE_FACES": "golden-faces-staging", "REGION": "us-east4"}
    out = subprocess.run([BASH, "-c", "source deploy/gcp/lib_faces.sh; faces_queue_state"], capture_output=True, text=True, env=env, cwd=Path(__file__).resolve().parent.parent)
    return out.stdout.strip()


def test_existing_queue(tmp_path):
    assert _state(tmp_path, 0, "") == "existe"


def test_missing_queue_is_reported_as_missing_not_as_an_error(tmp_path):
    assert _state(tmp_path, 1, "ERROR: (gcloud.tasks.queues.describe) NOT_FOUND: Queue does not exist.") == "falta"


@pytest.mark.parametrize("reason", ["ERROR: PERMISSION_DENIED: The caller does not have permission", "ERROR: (gcloud) Unable to reach the network"])
def test_permission_or_network_errors_are_never_swallowed(tmp_path, reason):
    state = _state(tmp_path, 1, reason)
    assert state.startswith("error:") and reason.split(": ", 1)[1][:20] in state


def test_deploy_script_stops_on_error_and_only_sets_the_variables_when_the_queue_exists():
    deploy = Path("deploy/gcp/deploy.sh").read_text(encoding="utf-8")
    assert "source deploy/gcp/lib_faces.sh" in deploy and 'if [ "$FACES_STATE" = "existe" ]; then' in deploy
    assert "exit 1" in deploy.split("FACES_STATE=")[1].split("esac")[0]                                # el caso de error detiene el despliegue
    assert ">/dev/null 2>&1; then      # cola de cálculos faciales" not in deploy                      # ya no se traga el error


def test_the_queue_script_grants_the_deployer_read_and_the_ops_account_the_wake_up_permissions():
    script = Path("deploy/gcp/faces_queue.sh").read_text(encoding="utf-8")
    assert "$(sa_email \"$SA_DEPLOYER\")\" --role roles/cloudtasks.viewer" in script
    assert "$(sa_email \"$SA_OPS\")\" --role roles/cloudtasks.enqueuer" in script and "roles/iam.serviceAccountUser" in script
