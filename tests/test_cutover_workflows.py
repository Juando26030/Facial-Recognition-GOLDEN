"""Los flujos de GitHub tras el corte a Cloud Run (docs/15 D2.5, docs/19): producción se despliega SOLO a mano (workflow_dispatch en `main` con confirm=DESPLEGAR; ningún push ni merge a `main` despliega), `main` NUNCA dispara el flujo de la VM
y staging solo se despliega a mano desde feat/** o saas/**."""
from pathlib import Path
from types import SimpleNamespace

import yaml

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _load(name):
    data = yaml.safe_load((WF / name).read_text(encoding="utf8"))
    data["on"] = data.pop(True, data.get("on"))              # PyYAML lee la clave `on` como True
    return data


def test_vm_workflow_is_manual_only_so_merging_to_main_never_deploys_the_vm():
    on = _load("deploy.yml")["on"]
    assert "push" not in on and "pull_request" not in on and "workflow_dispatch" in on


def test_cloud_run_workflow_deploys_staging_only_by_hand_and_production_only_by_hand_from_main():
    wf = _load("cloudrun.yml")
    assert "push" not in wf["on"]                                                # ningún push lanza este flujo (23-nov-2026: se quitó `migra/fase1-2`; el CI de ci.yml corre por su cuenta)
    jobs = wf["jobs"]
    # Staging solo A MANO (workflow_dispatch) desde `feat/**` y `saas/**`; nunca por push y nunca desde `main`.
    assert jobs["staging"]["if"] == ("github.event_name == 'workflow_dispatch' && "
                                     "(startsWith(github.ref, 'refs/heads/feat/') || startsWith(github.ref, 'refs/heads/saas/'))")
    assert jobs["staging"]["with"]["env"] == "staging" and jobs["staging"]["concurrency"] == {"group": "cloudrun-staging", "cancel-in-progress": False}
    assert jobs["production"]["with"]["env"] == "production" and jobs["production"]["needs"] == "test" and jobs["staging"]["needs"] == "test"
    confirm = wf["on"]["workflow_dispatch"]["inputs"]["confirm"]
    assert confirm["type"] == "string" and confirm["default"] == "" and "DESPLEGAR" in confirm["description"]
    assert wf["on"]["workflow_dispatch"]["inputs"]["force"]["default"] is False


def _production_runs(event, ref, confirm=""):
    """Evalúa la condición `if` del job `production` como lo haría GitHub Actions (solo usa `github.ref`, `github.event_name` e `inputs.confirm`)."""
    expr = _load("cloudrun.yml")["jobs"]["production"]["if"].replace("&&", " and ")
    return bool(eval(expr, {"__builtins__": {}}, {"github": SimpleNamespace(ref=ref, event_name=event), "inputs": SimpleNamespace(confirm=confirm)}))   # noqa: S307


def test_a_push_or_merge_to_main_never_reaches_the_production_job():
    main, mig = "refs/heads/main", "refs/heads/feat/x"
    assert _production_runs("push", main) is False and _production_runs("push", main, "DESPLEGAR") is False       # ni con el texto: un push no trae inputs
    assert _production_runs("pull_request", main) is False and _production_runs("push", mig) is False
    assert _production_runs("workflow_dispatch", main) is False                                                    # a mano pero sin confirmar
    assert _production_runs("workflow_dispatch", main, "desplegar") is False and _production_runs("workflow_dispatch", main, "SI") is False
    assert _production_runs("workflow_dispatch", mig, "DESPLEGAR") is False                                        # otra rama: nunca
    assert _production_runs("workflow_dispatch", main, "DESPLEGAR") is True                                        # la única forma
    assert "push" not in _load("cloudrun.yml")["on"] and "pull_request" not in _load("cloudrun.yml")["on"]


def test_only_the_vm_workflow_uses_the_self_hosted_runner():
    for p in WF.glob("*.yml"):
        for name, job in _load(p.name)["jobs"].items():
            runs_on = job.get("runs-on")
            assert (runs_on == "self-hosted") == (p.name == "deploy.yml" and name == "deploy"), f"{p.name}:{name} -> {runs_on}"
