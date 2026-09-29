"""deploy/gcp/check_bucket.py: lo que `move_region.sh verify` exige de un bucket nuevo (CORS, versiones, ciclo de vida) frente a los archivos reales del repositorio."""
import importlib.util
import json
import re

spec = importlib.util.spec_from_file_location("check_bucket", "deploy/gcp/check_bucket.py")
cb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cb)

ORIGIN = "https://app.example"


def describe(snake=False, app=True, backup=True, origin=ORIGIN, versioning=True):
    rules = (json.load(open("deploy/gcs-app-lifecycle.json"))["rule"] if app else []) + (json.load(open("deploy/gcs-lifecycle.json"))["rule"] if backup else [])
    cors = json.load(open("deploy/gcs-app-cors.json"))
    cors[0]["origin"] = [origin]
    doc = {"cors_config": cors, "lifecycle_config": {"rule": rules}, "versioning": {"enabled": versioning}}
    if snake:                                                  # gcloud a veces devuelve snake_case dentro de las reglas
        doc = json.loads(re.sub(r'"(matchesPrefix|daysSinceNoncurrentTime)"', lambda m: '"' + re.sub(r"([A-Z])", r"_\1", m.group(1)).lower() + '"', json.dumps(doc)))
    return doc


def failed(doc, kind):
    return [label for label, ok in cb.check(doc, kind, [ORIGIN]) if not ok]


def test_repo_lifecycle_and_cors_satisfy_every_check_in_both_key_styles():
    for snake in (False, True):
        assert failed(describe(snake), "both") == []
        assert failed(describe(snake, backup=False), "app") == []
        assert failed(describe(snake, app=False), "backup") == []


def test_missing_pieces_are_reported():
    assert "versiones de objeto activadas" in failed(describe(versioning=False), "app")
    assert any("CORS" in f for f in failed(describe(origin="https://otro.example"), "app"))
    assert "uploads/ se borra a 1 día" in failed(describe(app=False), "app")                 # sin las reglas de la app
    assert "db/ (diarios) se borra a los 30 días" in failed(describe(backup=False), "backup")


def test_backup_retention_is_30_days_not_60():
    doc = describe()
    for r in doc["lifecycle_config"]["rule"]:
        if r["condition"].get("age") == 30 and r["condition"].get("matchesPrefix") == ["db/"]:
            r["condition"]["age"] = 60
    assert "db/ (diarios) se borra a los 30 días" in failed(doc, "backup")
