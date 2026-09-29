"""Comprueba la configuración de un bucket de Golden a partir de `gcloud storage buckets describe gs://<bucket> --format=json` (entrada estándar).

    gcloud storage buckets describe "gs://$APP_BUCKET" --format=json | python3 deploy/gcp/check_bucket.py app https://app.golden-eventos.com [https://<sitio>.web.app ...]
    ... | python3 deploy/gcp/check_bucket.py backup     |     ... | python3 deploy/gcp/check_bucket.py both <origen>   (staging: un solo bucket con todo)

  app     CORS con PUT desde los orígenes indicados (subida directa con URL firmada), versiones de objeto, `uploads/` se borra a 1 día, versiones viejas de `biometric/` a 1 día,
          versiones viejas del resto a 30 días.
  backup  `db/hourly/` a 3 días y `db/` (diarios) a 30 días, y las versiones viejas de `db/` a 1 día.
Tolera los dos estilos de nombres de gcloud (camelCase o snake_case). Imprime `OK`/`FALTA` por comprobación; código de salida 1 si falta algo."""
import json
import sys


def norm(obj):
    """Claves en minúsculas y sin guiones bajos (matchesPrefix == matches_prefix), recursivo."""
    if isinstance(obj, dict):
        return {k.replace("_", "").lower(): norm(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [norm(v) for v in obj]
    return obj


def rules_of(doc: dict) -> list:
    lc = doc.get("lifecycleconfig") or doc.get("lifecycle") or {}
    return lc.get("rule", []) if isinstance(lc, dict) else []


def has_rule(rules: list, prefix: str, age=None, noncurrent=None) -> bool:
    for r in rules:
        if (r.get("action") or {}).get("type") != "Delete":
            continue
        c = r.get("condition") or {}
        prefixes = c.get("matchesprefix") or []
        if prefix and not any(prefix == p or p.endswith(prefix) for p in prefixes):
            continue
        if not prefix and prefixes:
            continue
        if age is not None and c.get("age") == age and c.get("dayssincenoncurrenttime") is None:
            return True
        if noncurrent is not None and c.get("dayssincenoncurrenttime") == noncurrent:
            return True
    return False


def versioning_on(doc: dict) -> bool:
    v = doc.get("versioning", doc.get("versioningenabled"))
    return bool(v.get("enabled")) if isinstance(v, dict) else bool(v)


def check(doc: dict, kind: str, origins: list) -> list:
    doc, rules, out = norm(doc), None, []
    rules = rules_of(doc)
    if kind in ("app", "both"):
        cors = doc.get("corsconfig") or doc.get("cors") or []
        put_origins = {o for c in cors if "PUT" in (c.get("method") or []) for o in (c.get("origin") or [])}
        for o in origins:
            out.append((f"CORS con PUT desde {o}", o in put_origins))
        out.append(("versiones de objeto activadas", versioning_on(doc)))
        out.append(("uploads/ se borra a 1 día", has_rule(rules, "uploads/", age=1)))
        out.append(("versiones viejas de biometric/ a 1 día", has_rule(rules, "biometric/", noncurrent=1)))
        out.append(("versiones viejas del resto a 30 días", has_rule(rules, "", noncurrent=30)))
    if kind in ("backup", "both"):
        out.append(("db/hourly/ se borra a los 3 días", has_rule(rules, "db/hourly/", age=3)))
        out.append(("db/ (diarios) se borra a los 30 días", has_rule(rules, "db/", age=30)))
        out.append(("versiones viejas de db/ a 1 día", has_rule(rules, "db/", noncurrent=1)))
    return out


def main(argv: list) -> int:
    if len(argv) < 2 or argv[1] not in ("app", "backup", "both"):
        print(__doc__)
        return 2
    results = check(json.load(sys.stdin), argv[1], argv[2:])
    for label, ok in results:
        print(f"  {'OK   ' if ok else 'FALTA'} {label}")
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
