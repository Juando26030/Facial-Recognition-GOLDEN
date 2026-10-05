"""Los flujos de GitHub tras el corte a Cloud Run (docs/15 D2.5, docs/19): `main` despliega producción en Cloud Run y NUNCA dispara el flujo de la VM; la rama de migración sigue desplegando staging."""
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _load(name):
    data = yaml.safe_load((WF / name).read_text(encoding="utf8"))
    data["on"] = data.pop(True, data.get("on"))              # PyYAML lee la clave `on` como True
    return data


def test_vm_workflow_is_manual_only_so_merging_to_main_never_deploys_the_vm():
    on = _load("deploy.yml")["on"]
    assert "push" not in on and "pull_request" not in on and "workflow_dispatch" in on


def test_cloud_run_workflow_deploys_staging_from_the_migration_branch_and_production_from_main():
    wf = _load("cloudrun.yml")
    assert set(wf["on"]["push"]["branches"]) == {"migra/fase1-2", "main"}
    jobs = wf["jobs"]
    assert jobs["staging"]["if"] == "github.ref == 'refs/heads/migra/fase1-2'" and jobs["staging"]["with"]["env"] == "staging"
    assert jobs["production"]["if"] == "github.ref == 'refs/heads/main'" and jobs["production"]["with"]["env"] == "production"
    assert jobs["production"]["needs"] == "test" and jobs["staging"]["needs"] == "test"


def test_only_the_vm_workflow_uses_the_self_hosted_runner():
    for p in WF.glob("*.yml"):
        for name, job in _load(p.name)["jobs"].items():
            runs_on = job.get("runs-on")
            assert (runs_on == "self-hosted") == (p.name == "deploy.yml" and name == "deploy"), f"{p.name}:{name} -> {runs_on}"
