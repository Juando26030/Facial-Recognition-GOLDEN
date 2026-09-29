"""Los valores con comas nunca pueden ir en --set-env-vars / --update-env-vars sin delimitador alterno: gcloud usa la coma como separador de variables
(«Bad syntax for dict arg», visto con LOAD_ALLOWED_HOSTS). Aquí no se toca la nube: se revisan los scripts y se corre run_phase4.sh con un `gcloud` de mentira."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.load_cfg import check_host

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")
FLAG = re.compile(r"--(?:set|update|set-build)-env-vars(?:\s+|=)(\"[^\"]*\"|'[^']*'|\S+)")


def _inline_env_flags(text: str):
    return [m.group(1).strip("\"'") for m in FLAG.finditer(text)]


def _bad(value: str) -> bool:
    """¿Lleva una coma sin delimitador alterno (`^X^`) al inicio? (`--set-env-vars "^@^A=x,y@B=z"` es la forma segura)."""
    return "," in value and not re.match(r"^\^.+?\^", value)


def test_no_script_or_doc_passes_a_comma_value_inline():
    offenders = []
    for path in list((ROOT / "deploy").rglob("*.sh")) + list((ROOT / "docs").glob("*.md")) + [ROOT / "README.md"]:
        if not path.exists() or path.name == "historial.md":
            continue
        for value in _inline_env_flags(path.read_text(encoding="utf8", errors="replace")):
            if _bad(value):
                offenders.append(f"{path.relative_to(ROOT)}: {value[:80]}")
    assert not offenders, "valores con coma en --set/--update-env-vars: " + "; ".join(offenders)


def test_lint_catches_the_original_bug_and_accepts_the_safe_forms():
    bad = 'gcloud run jobs deploy j --set-env-vars "A=1,LOAD_ALLOWED_HOSTS=a.run.app,b.run.app,C=3" --quiet'
    assert [_bad(v) for v in _inline_env_flags(bad)] == [True]                                   # las comas de una LISTA dentro de un valor se detectan solo por contexto…
    assert _bad("X=a,b") and not _bad("^@^X=a,b@Y=z") and not _bad("PUBLIC_LIMIT_FACTOR=200")


def test_job_env_writer_keeps_commas_equals_and_spaces_intact(tmp_path):
    out = tmp_path / "env.json"
    hosts = "golden-staging-1.web.app,golden-web-staging-1.us-east4.run.app,golden-publico-staging-1.us-east4.run.app"
    r = subprocess.run([sys.executable, "deploy/loadtest/job_env.py", str(out), f"LOAD_ALLOWED_HOSTS={hosts}", "LOAD_X=a=b c", "LOAD_USERS=500"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    env = json.loads(out.read_text(encoding="utf8"))
    assert env == {"LOAD_ALLOWED_HOSTS": hosts, "LOAD_X": "a=b c", "LOAD_USERS": "500"} and all(isinstance(v, str) for v in env.values())
    assert subprocess.run([sys.executable, "deploy/loadtest/job_env.py", str(out), "sin-igual"], cwd=ROOT, capture_output=True, text=True).returncode == 2


# ------------------------------------------------------------------ run_phase4.sh con un gcloud de mentira (sin nube)
FAKE_GCLOUD = r'''#!/usr/bin/env bash
args=("$@")
case "$1 $2" in
  "config get-value") case "$3" in project) echo goldenweb-staging;; run/region) echo us-east4;; esac ;;
  "projects describe") echo 298291650070 ;;
  "run jobs")
    if [ "$3" = deploy ]; then
      printf 'DEPLOY %s\n' "$*" >> "$FAKE_GCLOUD_LOG"
      for ((i = 0; i < ${#args[@]}; i++)); do
        [ "${args[i]}" = "--env-vars-file" ] && printf 'ENVFILE %s\n' "$(tr -d '\r\n' < "${args[i+1]}")" >> "$FAKE_GCLOUD_LOG"
      done
    elif [ "$3" = execute ]; then printf 'EXECUTE %s\n' "$*" >> "$FAKE_GCLOUD_LOG"; echo "exec-$4"; fi ;;
esac
exit 0
'''
WEB = "https://golden-staging-298291650070.web.app"
ALLOWED = ["golden-staging-298291650070.web.app", "golden-web-staging-298291650070.us-east4.run.app",
           "golden-publico-staging-298291650070.us-east4.run.app", "golden-biometria-staging-298291650070.us-east4.run.app"]


def _run(tmp_path, *script_args, web=WEB, extra_env=None):
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    gcloud = fake / "gcloud"
    gcloud.write_text(FAKE_GCLOUD, encoding="utf8", newline="\n")
    gcloud.chmod(gcloud.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "gcloud.log"
    log.write_text("", encoding="utf8")
    env = {**os.environ, "PATH": str(fake) + os.pathsep + os.environ["PATH"], "FAKE_GCLOUD_LOG": str(log), "PYTHON3": sys.executable, "WEB_URL": web,
           "LOAD_EVENT_ID": "7", "HOME": str(tmp_path), **(extra_env or {})}
    env.pop("REGION", None)
    r = subprocess.run([BASH, "deploy/loadtest/run_phase4.sh", *script_args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    return r, log.read_text(encoding="utf8").splitlines()


def _jobs(lines):
    deploys = [ln for ln in lines if ln.startswith("DEPLOY ")]
    envs = [json.loads(ln[len("ENVFILE "):]) for ln in lines if ln.startswith("ENVFILE ")]
    return deploys, envs


@pytest.mark.skipif(BASH is None, reason="sin bash")
@pytest.mark.parametrize("mode,users", [("small", ("500", "10", "3")), ("full", ("10000", "200", "60"))])
def test_every_generator_job_gets_its_env_from_a_file_with_the_comma_list_intact(tmp_path, mode, users):
    r, lines = _run(tmp_path, "run", *(["small"] if mode == "small" else []))
    assert r.returncode == 0, r.stdout + r.stderr
    deploys, envs = _jobs(lines)
    assert len(deploys) == 3 and len(envs) == 3
    for line in deploys:
        assert "--env-vars-file" in line and "--set-env-vars" not in line and "--update-env-vars" not in line        # ningún valor en línea de comandos
        assert "--set-secrets OPS_TOKEN=golden-ops-token-staging:latest" in line and "--region us-east4" in line
    by_scenario = {e["LOAD_SCENARIO"]: e for e in envs}
    assert set(by_scenario) == {"forms", "cedula", "face"}
    assert tuple(by_scenario[s]["LOAD_USERS"] for s in ("forms", "cedula", "face")) == users
    for env in envs:
        hosts = env["LOAD_ALLOWED_HOSTS"].split(",")                     # como lo lee deploy/loadtest/run_task.py
        assert sorted(hosts) == sorted(ALLOWED) and env["LOAD_HOST"] == WEB and env["LOAD_EVENT_ID"] == "7" and env["LOAD_FORM_SLUG"] == "carga"
        assert check_host(env["LOAD_HOST"], hosts) is None              # run_task acepta este destino…
        assert check_host("https://app.golden-eventos.com", hosts) is not None      # …y no el de producción
    assert sum(ln.startswith("EXECUTE ") for ln in lines) == 3


@pytest.mark.skipif(BASH is None, reason="sin bash")
def test_only_selects_scenarios_and_a_wrong_web_url_deploys_nothing(tmp_path):
    r, lines = _run(tmp_path, "run", "small", extra_env={"ONLY": "forms,cedula"})
    deploys, envs = _jobs(lines)
    assert r.returncode == 0 and sorted(e["LOAD_SCENARIO"] for e in envs) == ["cedula", "forms"] and len(deploys) == 2
    for wrong in ("https://app.golden-eventos.com", "https://golden-staging-999.web.app", "https://golden-staging-298291650070.web.app.evil.example"):
        r, lines = _run(tmp_path, "run", "small", web=wrong)
        assert r.returncode != 0 and "NO es un destino de staging permitido" in r.stderr and not [ln for ln in lines if ln.startswith(("DEPLOY", "EXECUTE"))], wrong
