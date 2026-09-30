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
printf 'CALL %s
' "$*" >> "$FAKE_GCLOUD_LOG"
case "$1 $2" in
  "config get-value") case "$3" in project) echo goldenweb-staging;; run/region) echo us-east4;; esac ;;
  "projects describe") echo 298291650070 ;;
  "run services") [ "$3" = describe ] && { f="$FAKE_SERVICES_DIR/$4.json"; if [ -f "$f" ]; then cat "$f"; else echo '{}'; fi; } ;;
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


def _service_json(max_scale, factor=None):
    """Forma v1 de `gcloud run services describe --format=json` (lo que importa: maxScale y las variables de la plantilla)."""
    env = [{"name": "APP_MODULE", "value": "x"}] + ([{"name": "PUBLIC_LIMIT_FACTOR", "value": str(factor)}] if factor is not None else [])
    return {"spec": {"template": {"metadata": {"annotations": {"autoscaling.knative.dev/maxScale": str(max_scale)}}, "spec": {"containers": [{"env": env}]}}}}


GOOD_SERVICES = {"golden-web-staging": _service_json(10), "golden-publico-staging": _service_json(10, 200), "golden-biometria-staging": _service_json(10)}


def _run(tmp_path, *script_args, web=WEB, extra_env=None, services=None):
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    gcloud = fake / "gcloud"
    gcloud.write_text(FAKE_GCLOUD, encoding="utf8", newline="\n")
    gcloud.chmod(gcloud.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "gcloud.log"
    log.write_text("", encoding="utf8")
    svc_dir = tmp_path / "services"
    svc_dir.mkdir(exist_ok=True)
    for name, body in {**GOOD_SERVICES, **(services or {})}.items():
        (svc_dir / f"{name}.json").write_text(json.dumps(body), encoding="utf8")
    # HERMÉTICO: el script NO hereda nada del entorno de quien corre las pruebas. conftest.py fija PUBLIC_BASE_URL="http://test.local" en el proceso de pytest y el CI trae
    # DATABASE_URL, SECRET_KEY, etc.; config.sh respeta PUBLIC_BASE_URL/FIREBASE_SITE/APP_BUCKET/REGION/PROJECT_ID… si existen, y eso cambiaba los hosts permitidos.
    # Solo pasan: PATH (con el gcloud de mentira primero), lo mínimo del sistema (Windows necesita SYSTEMROOT/TEMP para bash y mktemp) y lo que el test declara.
    keep = {k: os.environ[k] for k in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "COMSPEC", "MSYSTEM") if k in os.environ}
    env = {**keep, "PATH": str(fake) + os.pathsep + os.environ["PATH"], "HOME": str(tmp_path), "FAKE_GCLOUD_LOG": str(log), "FAKE_SERVICES_DIR": str(svc_dir), "PYTHONIOENCODING": "utf-8", "PYTHON3": sys.executable, "WEB_URL": web,
           "LOAD_EVENT_ID": "7", **(extra_env or {})}
    r = subprocess.run([BASH, "deploy/loadtest/run_phase4.sh", *script_args], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf8", errors="replace", timeout=120)
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
def test_inherited_environment_can_neither_widen_nor_break_the_allowed_hosts(tmp_path, monkeypatch):
    """El CI (y conftest.py) traen PUBLIC_BASE_URL=http://test.local; una terminal de producción podría traer el de producción. Nada de eso entra en la lista de destinos permitidos:
    run_phase4.sh la calcula SOLO desde proyecto, región y nombres de staging."""
    poison = {"PUBLIC_BASE_URL": "http://test.local", "FIREBASE_SITE": "otro-sitio", "GOLDEN_ENV": "production", "APP_BUCKET": "x", "PROJECT_ID": "otro-proyecto"}
    for key, value in poison.items():
        monkeypatch.setenv(key, value)                                  # también en el proceso de pytest: _run no debe heredarlos
    r, lines = _run(tmp_path, "run", "small")
    _, envs = _jobs(lines)
    assert r.returncode == 0, r.stdout + r.stderr
    assert all(sorted(e["LOAD_ALLOWED_HOSTS"].split(",")) == sorted(ALLOWED) for e in envs)
    # Y aunque el entorno SÍ llegara al script (una terminal con PUBLIC_BASE_URL de producción), el candado sigue cerrado: ese host no pasa ni el 2.º candado (load_cfg.check_host).
    prod = "https://app.golden-eventos.com"
    r, lines = _run(tmp_path, "run", "small", web=prod, extra_env={"PUBLIC_BASE_URL": prod, "FIREBASE_SITE": "golden-app-298291650070"})
    assert r.returncode != 0 and not [ln for ln in lines if ln.startswith(("DEPLOY", "EXECUTE"))]
    assert check_host(prod, [prod.replace("https://", "")]) is not None and check_host("https://golden-app-298291650070.web.app", ["golden-app-298291650070.web.app"]) is not None


@pytest.mark.skipif(BASH is None, reason="sin bash")
def test_only_selects_scenarios_and_a_wrong_web_url_deploys_nothing(tmp_path):
    r, lines = _run(tmp_path, "run", "small", extra_env={"ONLY": "forms,cedula"})
    deploys, envs = _jobs(lines)
    assert r.returncode == 0 and sorted(e["LOAD_SCENARIO"] for e in envs) == ["cedula", "forms"] and len(deploys) == 2
    for wrong in ("https://app.golden-eventos.com", "https://golden-staging-999.web.app", "https://golden-staging-298291650070.web.app.evil.example"):
        r, lines = _run(tmp_path, "run", "small", web=wrong)
        assert r.returncode != 0 and "NO es un destino de staging permitido" in r.stderr and not [ln for ln in lines if ln.startswith(("DEPLOY", "EXECUTE"))], wrong


# ------------------------------------------------------------------ comprobación previa de `run` y protección de los originales de scale-up
@pytest.mark.skipif(BASH is None, reason="sin bash")
@pytest.mark.parametrize("services,needle", [
    ({"golden-publico-staging": _service_json(10)}, "PUBLIC_LIMIT_FACTOR = sin definir, esperado 200"),               # un despliegue de CI borró el factor
    ({"golden-publico-staging": _service_json(10, 1)}, "PUBLIC_LIMIT_FACTOR = 1, esperado 200"),
    ({"golden-biometria-staging": _service_json(6)}, "golden-biometria-staging: máximo de instancias = 6, esperado 10"),      # un tope viejo de 6 sin subir
    ({"golden-web-staging": _service_json(3)}, "golden-web-staging: máximo de instancias = 3, esperado 10"),
    ({"golden-publico-staging": {}}, "máximo de instancias = sin definir"),
])
def test_run_aborts_before_creating_anything_when_a_deploy_wiped_the_load_settings(tmp_path, services, needle):
    r, lines = _run(tmp_path, "run", "small", services=services)
    assert r.returncode != 0 and needle in r.stderr and "No se lanzó nada" in r.stderr
    assert not [ln for ln in lines if ln.startswith(("DEPLOY", "EXECUTE"))]                # ningún Job creado ni lanzado


@pytest.mark.skipif(BASH is None, reason="sin bash")
def test_run_passes_the_preflight_with_the_expected_settings_custom_caps_and_the_explicit_skip(tmp_path):
    assert _run(tmp_path, "run", "small")[0].returncode == 0                                # 200 y máximos 10 (los de producción): pasa
    caps = {"golden-web-staging": _service_json(4), "golden-publico-staging": _service_json(4, 200), "golden-biometria-staging": _service_json(8)}
    r, _ = _run(tmp_path, "run", "small", services=caps, extra_env={"SCALE_WEB": "2 4", "SCALE_PUBLICO": "2 4", "SCALE_BIO": "3 8"})
    assert r.returncode == 0, r.stderr                                                    # los máximos esperados salen de SCALE_* (los mismos de scale-up)
    r, lines = _run(tmp_path, "run", "small", services={"golden-publico-staging": _service_json(10)}, extra_env={"PREFLIGHT_SKIP": "1"})
    assert r.returncode == 0 and "PREFLIGHT_SKIP=1" in r.stderr and len([ln for ln in lines if ln.startswith("DEPLOY")]) == 3     # omitirla es explícito y deja aviso


def test_preflight_script_reads_both_api_shapes():
    import importlib.util
    spec = importlib.util.spec_from_file_location("preflight", ROOT / "deploy/loadtest/preflight.py")
    pf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pf)
    v2 = {"template": {"scaling": {"maxInstanceCount": 6}, "containers": [{"env": [{"name": "PUBLIC_LIMIT_FACTOR", "value": "200"}]}]}}
    assert pf.problems(v2, "s", 6, 200) == [] and pf.problems(_service_json(6, 200), "s", 6, 200) == []
    assert len(pf.problems(v2, "s", 4, 100)) == 2 and pf.problems({}, "s", 6)                       # vacío = problema, nunca «todo bien»


@pytest.mark.skipif(BASH is None, reason="sin bash")
def test_scale_up_refuses_to_overwrite_the_saved_originals(tmp_path):
    saved = tmp_path / ".golden_phase4_scale_goldenweb-staging.txt"
    saved.write_text("golden-web-staging 0 10\ngolden-publico-staging 2 10\ngolden-biometria-staging 1 10\n", encoding="utf8")
    before = saved.read_text(encoding="utf8")
    r, lines = _run(tmp_path, "scale-up")
    assert r.returncode != 0 and "scale-up SE NIEGA" in r.stderr and "scale-down" in r.stderr and "reescribiría los originales" in r.stderr
    assert saved.read_text(encoding="utf8") == before                                     # los originales quedan INTACTOS
    assert not [ln for ln in lines if "services update" in ln]                            # y no se tocó ningún servicio


def _fake_curl(tmp_path):
    """scale-up lee y mueve el mínimo por la API REST con curl: uno de mentira (lee «min 0, max 10», ignora lo demás)."""
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    curl = fake / "curl"
    body = "#!/usr/bin/env bash\necho '{\"scaling\":{\"minInstanceCount\":0},\"template\":{\"scaling\":{\"maxInstanceCount\":10}}}'\n"
    curl.write_text(body, encoding="utf8", newline="\n")
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)


def _max_instances(lines):
    return {ln.split()[4]: ln.split("--max-instances ")[1].split()[0] for ln in lines if "services update" in ln and "--max-instances" in ln}


@pytest.mark.skipif(BASH is None, reason="sin bash")
def test_scale_up_defaults_to_the_production_max_of_10_and_takes_caps_from_the_variables(tmp_path):
    _fake_curl(tmp_path)
    r, lines = _run(tmp_path, "scale-up")
    assert r.returncode == 0, r.stderr
    assert _max_instances(lines) == {"golden-web-staging": "10", "golden-publico-staging": "10", "golden-biometria-staging": "10"}         # sin recorte a 6
    (tmp_path / ".golden_phase4_scale_goldenweb-staging.txt").unlink()
    r, lines = _run(tmp_path, "scale-up", extra_env={"SCALE_WEB": "1 4", "SCALE_PUBLICO": "2 8", "SCALE_BIO": "3 5"})
    assert r.returncode == 0, r.stderr
    assert _max_instances(lines) == {"golden-web-staging": "4", "golden-publico-staging": "8", "golden-biometria-staging": "5"}


@pytest.mark.skipif(BASH is None, reason="sin bash")
@pytest.mark.parametrize("value,expected", [(None, "0.5"), ("1", "1"), ("0.25", "0.25"), ("1.0", "1.0")])
def test_submit_ratio_reaches_every_job_and_defaults_to_half(tmp_path, value, expected):
    r, lines = _run(tmp_path, "run", "small", extra_env={"LOAD_SUBMIT_RATIO": value} if value else None)
    assert r.returncode == 0, r.stdout + r.stderr
    _, envs = _jobs(lines)
    assert len(envs) == 3 and all(e["LOAD_SUBMIT_RATIO"] == expected for e in envs)
    assert f"envían el {round(100 * float(expected))} % de quienes abren" in r.stdout


@pytest.mark.skipif(BASH is None, reason="sin bash")
@pytest.mark.parametrize("bad", ["2", "-1", "abc", "0,5", "1.5", "50"])
def test_invalid_submit_ratio_creates_nothing(tmp_path, bad):
    r, lines = _run(tmp_path, "run", "small", extra_env={"LOAD_SUBMIT_RATIO": bad})
    assert r.returncode != 0 and "LOAD_SUBMIT_RATIO" in r.stderr and "No se lanzó nada" in r.stderr
    assert not [ln for ln in lines if ln.startswith(("DEPLOY", "EXECUTE"))]


def test_submit_ratio_parser(monkeypatch):
    from scripts.load_cfg import DEFAULT_SUBMIT_RATIO, submit_ratio
    monkeypatch.delenv("LOAD_SUBMIT_RATIO", raising=False)
    assert submit_ratio() == DEFAULT_SUBMIT_RATIO == 0.5
    for raw, want in (("1", 1.0), ("0", 0.0), ("0.25", 0.25), (" 0.7 ", 0.7), ("", 0.5)):
        monkeypatch.setenv("LOAD_SUBMIT_RATIO", raw)
        assert submit_ratio() == want
    for bad in ("2", "-0.1", "abc", "nan", "1,5"):
        monkeypatch.setenv("LOAD_SUBMIT_RATIO", bad)
        with pytest.raises(SystemExit):
            submit_ratio()
