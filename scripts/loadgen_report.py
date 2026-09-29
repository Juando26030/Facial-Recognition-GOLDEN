"""Une los resultados de las tareas de un Job generador (líneas `LOADGEN_RESULT {json}` de sus logs) y los compara con los criterios de la Fase 4 (docs/13 §11).

    gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="golden-loadgen-staging" AND labels."run.googleapis.com/execution_name"="<EJECUCION>" AND textPayload:"LOADGEN_RESULT"' \
        --project goldenweb-staging --format=json --limit 1000 > forms.json
    python scripts/loadgen_report.py forms.json cedula.json face.json          # uno o varios archivos (JSON de gcloud o texto plano con las líneas)

Los percentiles salen de los histogramas UNIDOS de todas las tareas (exactos al milisegundo que redondea Locust), no de promediar percentiles. Sin datos personales."""
import json
import sys

CRITERIA = {   # escenario: (petición que se juzga, p95 máximo en ms)
    "forms": ("POST envio", 2000),
    "cedula": ("POST checkin-cedula", 500),
    "face": ("POST recognize", 2000),
}


def parse(path: str) -> list:
    raw = open(path, encoding="utf8").read()
    lines = []
    try:
        for entry in json.loads(raw):
            text = entry.get("textPayload") or (entry.get("jsonPayload") or {}).get("message") or ""
            lines.append(text)
    except (ValueError, AttributeError):
        lines = raw.splitlines()
    return [json.loads(line.split("LOADGEN_RESULT ", 1)[1]) for line in lines if "LOADGEN_RESULT " in line]


def percentile(hist: dict, q: float) -> int:
    total = sum(hist.values())
    if not total:
        return 0
    need, seen = total * q, 0
    for ms in sorted(hist):
        seen += hist[ms]
        if seen >= need:
            return ms
    return max(hist)


def merge(results: list) -> dict:
    out = {}
    for r in results:
        for e in r["entries"]:
            m = out.setdefault(e["name"], {"requests": 0, "failures": 0, "max_ms": 0, "hist": {}})
            m["requests"] += e["requests"]
            m["failures"] += e["failures"]
            m["max_ms"] = max(m["max_ms"], e["max_ms"] or 0)
            for ms, n in e["histogram"].items():
                m["hist"][int(ms)] = m["hist"].get(int(ms), 0) + n
    return out


def main(paths: list) -> int:
    by_scenario = {}
    for p in paths:
        for r in parse(p):
            by_scenario.setdefault(r["scenario"], []).append(r)
    if not by_scenario:
        print("No hay líneas LOADGEN_RESULT en los archivos.")
        return 2
    verdict = 0
    for scenario, results in by_scenario.items():
        merged, errors = merge(results), {}
        for r in results:
            for k, v in r["errors"].items():
                errors[k] = errors.get(k, 0) + v
        tasks = {(r["task"], r["tasks"]) for r in results}
        print(f"\n### {scenario}: {len(tasks)} tarea(s), {sum(r['users'] for r in results)} usuarios virtuales, ~{max(r['seconds'] for r in results)} s\n")
        print("| Petición | Solicitudes | Fallos | p50 ms | p95 ms | p99 ms | máx ms |\n|---|---:|---:|---:|---:|---:|---:|")
        for name, m in sorted(merged.items()):
            print(f"| {name} | {m['requests']} | {m['failures']} | {percentile(m['hist'], .5)} | {percentile(m['hist'], .95)} | {percentile(m['hist'], .99)} | {m['max_ms']:.0f} |")
        gens = [(r["task"], r.get("generator")) for r in results if r.get("generator")]
        if gens:
            print("\nGenerador (si la CPU pasa de ~85 % o el retraso p95 de ~200 ms, la latencia medida incluye la espera del PROPIO generador y no vale como latencia del servidor):")
            for task, g in sorted(gens):
                flag = "  ⚠ SATURADO" if g["cpu_pct"] > 85 or g["lag_p95_ms"] > 200 else ""
                print(f"- tarea {task}: CPU {g['cpu_pct']} %, retraso del bucle p95 {g['lag_p95_ms']} ms, máx {g['lag_max_ms']} ms{flag}")
        if errors:
            print("\nFallos por motivo:\n" + "\n".join(f"- {v} × {k}" for k, v in sorted(errors.items(), key=lambda kv: -kv[1])[:10]))
        target, limit = CRITERIA.get(scenario, (None, None))
        m = merged.get(target)
        five_xx = sum(v for k, v in errors.items() if any(f" {c}" in k or f"submit {c}" in k or f"{c} " in k for c in ("500", "502", "503", "504")))
        if m:
            p95 = percentile(m["hist"], .95)
            ok = p95 < limit and m["failures"] == 0 if scenario != "face" else p95 < limit
            print(f"\nCriterio {scenario}: p95 de «{target}» < {limit} ms → {p95} ms; fallos {m['failures']}; 5xx {five_xx} → {'CUMPLE' if ok and not five_xx else 'NO CUMPLE'}"
                  + (" (facial: los 503 «reintenta» son contención esperada, revisar cuántos)" if scenario == "face" else ""))
            verdict |= 0 if ok and not five_xx else 1
    print("\nFalta el resto de criterios que salen de la base: corre el paso `--verify` de scripts.seed_load_staging (cupo, duplicados) y compara la latencia de cédula "
          "sola contra la de cédula durante el pico de formularios (aislamiento: no más de +20 %).")
    return verdict


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
