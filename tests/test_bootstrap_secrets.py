"""Reejecución del bootstrap con secretos que ya existen (deploy/gcp/lib_secrets.sh): no regenera ni agrega versión a lo que ya tiene valor, los opcionales con Enter son seguros y el resumen dice
qué secretos tienen versión. Aquí no se toca la nube: un `gcloud` de mentira guarda los secretos en una carpeta temporal."""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="sin bash")
ROOT = Path(__file__).resolve().parent.parent

FAKE_GCLOUD = r'''#!/usr/bin/env bash
S="$FAKE_SECRETS"; echo "$*" >> "$FAKE_LOG"
case "$1 $2 $3" in
  "secrets versions access") n="${@: -1}"; ls "$S/$n"/v* >/dev/null 2>&1 || exit 1; cat "$S/$n/$(ls "$S/$n" | sort | tail -1)" ;;
  "secrets versions add") n="$4"; mkdir -p "$S/$n"; k=$(ls "$S/$n" | wc -l); cat > "$S/$n/v$((k+1))" ;;
  "secrets describe "*) [ -d "$S/$3" ] || exit 1 ;;
  "secrets create "*) mkdir -p "$S/$3" ;;
  *) exit 0 ;;
esac
'''

OPTIONALS = ("wompi-public-key wompi-integrity-secret wompi-events-secret wompi-private-key wompi-sandbox-public-key wompi-sandbox-integrity-secret wompi-sandbox-events-secret "
             "wompi-sandbox-private-key azure-tenant-id azure-client-id azure-client-secret graph-sender alert-email neon-api-key neon-project-id neon-endpoint-id")
# la misma secuencia que bootstrap.sh (paso 5), con FRESH_START=1
SEQUENCE = f'''
put_secret direct-database-url "cadena" 1
put_secret secret-key "gen" 1 gen_hex
put_secret face-encryption-key "gen" 1 gen_fernet
put_secret ops-token "gen" 1 gen_hex
for opt in {OPTIONALS}; do put_secret "$opt" "opcional" 0; done
'''


def _run(tmp_path, existing: dict, stdin: str, script: str = SEQUENCE, rotate: str = "", containers=()):
    secrets = tmp_path / "secrets"
    secrets.mkdir(exist_ok=True)
    for name, value in existing.items():
        (secrets / f"golden-{name}").mkdir(parents=True, exist_ok=True)
        (secrets / f"golden-{name}" / "v1").write_text(value, encoding="utf-8")
    for name in containers:                              # el secreto existe pero no tiene ninguna versión (quedó así tras el fallo del 9-oct)
        (secrets / f"golden-{name}").mkdir(parents=True, exist_ok=True)
    fake = tmp_path / "gcloud"
    fake.write_text(FAKE_GCLOUD, encoding="utf-8", newline="\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"
    log.write_text("", encoding="utf-8")
    prog = f'''set -e
secret_name() {{ echo "golden-$1"; }}
ok() {{ echo "   ✓ $*"; }}
exists() {{ "$@" >/dev/null 2>&1; }}
ROTATE="{rotate}"
source deploy/gcp/lib_secrets.sh
gen_hex() {{ echo GENERADO-HEX; }}; gen_fernet() {{ echo GENERADO-FERNET; }}
{script}
'''
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}", "FAKE_SECRETS": str(secrets), "FAKE_LOG": str(log)}
    raw = subprocess.run([BASH, "-c", prog], input=stdin.encode("utf-8"), capture_output=True, env=env, cwd=ROOT)      # bytes: en Windows el modo texto convertiría cada salto de línea en CR+LF y `read` guardaría un valor vacío como "\r"
    out = type("R", (), {"returncode": raw.returncode, "stdout": raw.stdout.decode("utf-8", "replace"), "stderr": raw.stderr.decode("utf-8", "replace")})
    return out, log.read_text(encoding="utf-8"), secrets


def _versions(secrets: Path, name: str) -> list:
    d = secrets / f"golden-{name}"
    return sorted(p.name for p in d.glob("v*")) if d.exists() else []


EXISTING = {"direct-database-url": "postgresql://dueno", "secret-key": "SK", "face-encryption-key": "LLAVE-DE-ROSTROS", "ops-token": "OPS", "alert-email": "a@b.co"}


def test_rerun_never_regenerates_or_adds_a_version_to_secrets_that_already_have_one(tmp_path):
    """El caso real: cinco secretos con valor, `golden-database-url` sin versión y todos los opcionales omitidos la primera vez."""
    out, log, secrets = _run(tmp_path, EXISTING, "\n" * 15, containers=("database-url",))
    assert out.returncode == 0, out.stderr
    for name in EXISTING:
        assert f"golden-{name} ya tiene valor" in out.stdout
        assert _versions(secrets, name) == ["v1"]                                         # ni una versión nueva
        assert f"ADD golden-{name}" not in log and f"versions add golden-{name}" not in log
    assert (secrets / "golden-face-encryption-key" / "v1").read_text(encoding="utf-8") == "LLAVE-DE-ROSTROS"      # la llave que ya copiaste no cambia
    assert "GENERADO" not in out.stdout and "generado al azar" not in out.stdout             # ningún generador corrió


def test_optionals_left_blank_again_are_asked_again_and_are_safe(tmp_path):
    out, log, secrets = _run(tmp_path, EXISTING, "\n" * 15)
    assert out.stdout.count("(omitido)") == 15                                              # 8 de Wompi + 4 de Microsoft + 3 de Neon; alert-email ya tenía valor
    for name in OPTIONALS.split():
        if name != "alert-email":
            assert not (secrets / f"golden-{name}").exists()                                # Enter = no se crea nada
    assert "secrets create" not in log and "versions add" not in log
    out2, log2, _ = _run(tmp_path, {}, "\n" * 15)                                           # y una tercera corrida da lo mismo
    assert out2.returncode == 0 and "secrets create" not in log2


def test_an_optional_can_be_filled_on_the_rerun(tmp_path):
    out, log, secrets = _run(tmp_path, EXISTING, "\n" * 12 + "KEY\nPROJ\nEP\n")
    assert out.returncode == 0, out.stderr
    assert (secrets / "golden-neon-api-key" / "v1").read_text(encoding="utf-8") == "KEY" and _versions(secrets, "neon-project-id") == ["v1"] and _versions(secrets, "neon-endpoint-id") == ["v1"]
    assert "KEY" not in out.stdout and "PROJ" not in out.stdout                              # los valores nunca se imprimen


def test_first_run_generates_each_required_secret_once_and_a_required_one_without_value_stops(tmp_path):
    out, log, secrets = _run(tmp_path, {}, "postgresql://dueno\n" + "\n" * 3 + "\n" * 16)
    assert out.returncode == 0, out.stderr
    assert (secrets / "golden-secret-key" / "v1").read_text(encoding="utf-8") == "GENERADO-HEX" and (secrets / "golden-face-encryption-key" / "v1").read_text(encoding="utf-8") == "GENERADO-FERNET"
    assert [_versions(secrets, n) for n in ("direct-database-url", "secret-key", "face-encryption-key", "ops-token")] == [["v1"]] * 4
    (tmp_path / "x").mkdir()
    blank, _, _ = _run(tmp_path / "x", {}, "\n", script='put_secret direct-database-url "cadena" 1')
    assert blank.returncode == 1 and "obligatorio" in blank.stderr


def test_rotate_asks_again_only_for_the_named_secret(tmp_path):
    out, log, secrets = _run(tmp_path, EXISTING, "nuevo-token\n" + "\n" * 15, rotate="ops-token")
    assert _versions(secrets, "ops-token") == ["v1", "v2"] and (secrets / "golden-ops-token" / "v2").read_text(encoding="utf-8") == "nuevo-token"
    assert _versions(secrets, "face-encryption-key") == ["v1"] and _versions(secrets, "secret-key") == ["v1"]


def test_the_final_summary_tells_for_each_secret_if_it_has_a_version(tmp_path):
    out, _, _ = _run(tmp_path, EXISTING, "\n" * 15, containers=("database-url",),
                     script=SEQUENCE + '\nsecrets_summary direct-database-url database-url face-encryption-key alert-email wompi-public-key neon-api-key')
    lines = out.stdout.splitlines()
    assert "   ✓ golden-direct-database-url: con versión" in lines and "   ✓ golden-face-encryption-key: con versión" in lines and "   ✓ golden-alert-email: con versión" in lines
    assert "   ✗ golden-database-url: existe pero SIN versión" in lines
    assert "   – golden-wompi-public-key: no existe (opcional omitido)" in lines and "   – golden-neon-api-key: no existe (opcional omitido)" in lines
    assert "LLAVE-DE-ROSTROS" not in out.stdout and "postgresql://dueno" not in out.stdout        # nunca valores


def test_bootstrap_uses_the_library_runs_the_role_script_with_rotate_when_the_secret_has_no_version_and_prints_the_summary():
    b = (ROOT / "deploy/gcp/bootstrap.sh").read_text(encoding="utf-8")
    assert "source deploy/gcp/lib_secrets.sh" in b and "put_secret() {" not in b                 # una sola definición
    assert 'if ! secret_has_version "$(secret_name database-url)" || [[ " $ROTATE " == *" database-url "* ]]; then' in b
    role = b.split('if ! secret_has_version "$(secret_name database-url)"', 1)[1].split("\nfi\n", 1)[0]
    assert "scripts/neon_app_role.py" in role and "--rotate" in role                               # restablece la contraseña de golden_app y guarda la cadena
    assert 'secret_has_version "$(secret_name database-url)" || {' in role and "exit 1" in role     # y si no quedó la versión, se detiene
    assert b.index("secrets_summary $SECRET_NAMES") < b.index("LISTO ($GOLDEN_ENV)")
