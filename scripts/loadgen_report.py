"""Une los resultados de las tareas de un Job generador (líneas `LOADGEN_RESULT {json}` de sus logs) y los compara con los criterios de la Fase 4 (docs/13 §11).

    gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="golden-loadgen-staging" AND labels."run.googleapis.com/execution_name"="<EJECUCION>" AND textPayload:"LOADGEN_RESULT"' \
        --project goldenweb-staging --format=json --limit 1000 > forms.json
    python scripts/loadgen_report.py forms.json cedula.json face.json          # uno o varios archivos (JSON de gcloud o texto plano con las líneas)

Los percentiles salen de los histogramas UNIDOS de todas las tareas (exactos al milisegundo que redondea Locust), no de promediar percentiles. Sin datos personales."""
import json
import sys

CRITERIA = {   # escenario: (petición que se juzga, p95 máximo en ms). «forms» tiene su propio criterio (forms_criteria, abajo)
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


USER_PREFIX = "[usuario] "          # resultado final de cada usuario virtual que envía (tests/load/locustfile.py::_user_result)
BACKPRESSURE = "(contrapresión"     # intentos «ocupado» con reintento: no son fallos


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


# Criterio de aprobación de FORMULARIOS (decidido con Juan David tras las corridas 5-7): lo que vive el usuario, no la latencia de un intento suelto.
STATE_P95_MS, STATE_P99_MS = 2000, 5000       # apertura (GET state): la página no cuenta (la sirve la CDN)
USER_P95_S, USER_P95_GOAL_S = 120, 60         # p95 del tiempo TOTAL de quien se inscribe (con todos sus reintentos); meta 60 s tras la función SQL única
USER_OK_PCT = 99.0                            # «inscrito» o «cupo lleno»
INFRA_MAX_PCT = 0.1                           # 503 sin marca «busy» de la app (HTML de Google) y 429 de infraestructura: tolerados hasta este % de los intentos si TODOS los usuarios terminan con resultado
MIRROR_PREFIX = "[fuera de la app] "          # espejos de latencia (locustfile::_outside_the_app): repiten respuestas que ya están contadas con su nombre real; NUNCA se suman al criterio
# Infraestructura = respuestas que NO vienen de la app: 502/503/504 cuyo cuerpo no es el JSON de la app (HTML de Google), 429 de texto plano, y peticiones sin respuesta (tiempo agotado / red).
INFRA_KINDS = ("502 infra", "503 infra", "504 infra", "429", "tiempo agotado", "error de red")


def parse_verify(path: str):
    """La línea `LOAD_VERIFY {json}` de `scripts/seed_load_staging.py --verify` (si está en alguno de los archivos)."""
    found = None
    for line in open(path, encoding="utf8").read().splitlines():
        if "LOAD_VERIFY " in line:
            try:
                found = json.loads(line.split("LOAD_VERIFY ", 1)[1])
            except ValueError:
                pass
    return found


def _kind(name: str) -> str:
    return name.split("(contrapresión ")[1].rstrip(")")              # «503», «503 infra», «503 app», «429», «502»…


def infra_checks(merged: dict, errors: dict, all_done: bool) -> list:
    """Los dos puntos del criterio sobre 5xx, comunes a formularios y cédula. Cada respuesta cuenta UNA vez (sin los espejos «[fuera de la app]»)."""
    real = {k: m for k, m in merged.items() if not k.startswith(MIRROR_PREFIX)}
    infra = sum(m["requests"] for k, m in real.items() if "(contrapresión" in k and _kind(k) in INFRA_KINDS)
    attempts = sum(m["requests"] for k, m in real.items() if not k.startswith(USER_PREFIX))
    infra_pct = 100 * infra / max(attempts, 1)
    checks = [(f"infraestructura (502/503/504 HTML de Google, 429 de texto plano, sin respuesta): {infra} de {attempts} intentos = {infra_pct:.3f} % (máximo {INFRA_MAX_PCT} %) y "
               f"{'todos' if all_done else 'NO todos'} los usuarios/escaneos terminaron con resultado", infra_pct <= INFRA_MAX_PCT and all_done)]
    other_5xx = sum(m["requests"] for k, m in real.items() if "(contrapresión" in k and _kind(k) not in INFRA_KINDS + ("503",))
    other_5xx += sum(v for k, v in errors.items() if any(f" {c}" in k for c in ("500", "501", "502", "503", "504", "505")))
    checks.append((f"{other_5xx} respuestas 5xx de la app (500, 502/503/504 JSON, 503 sin marca «busy»; 0 esperadas)", other_5xx == 0))
    return checks


def cedula_criteria(merged: dict, users: dict, errors: dict, gens: list, verify) -> int:
    """Criterio de la estación de cédula: p95 del primer intento < 500 ms sin fallos; infraestructura y 5xx como en formularios; todos los escaneos terminan con resultado;
    y, con la línea LOAD_VERIFY, ningún ingreso confirmado se pierde (registros en la base >= escaneos 200 del informe)."""
    checks = []
    m = merged.get("POST checkin-cedula")
    if m:
        p95 = percentile(m["hist"], .95)
        checks.append((f"p95 de «POST checkin-cedula» {p95} ms < 500 ms; fallos {m['failures']} (0 esperados)", p95 < 500 and m["failures"] == 0))
    total = sum(v["requests"] for v in users.values())
    done = sum(v["requests"] for k, v in users.items() if not k.endswith("sin resultado"))
    checks += infra_checks(merged, errors, all_done=done == total)
    ok200 = sum(v["requests"] - v["failures"] for k, v in merged.items() if k in ("POST checkin-cedula", "POST checkin-cedula (reintento)"))
    if verify and verify.get("access_logs_in_event") is not None:
        checks.append((f"base: ingresos registrados {verify['access_logs_in_event']} >= escaneos 200 del informe {ok200} (ninguno confirmado se pierde; de más = respuesta perdida tras guardar)",
                       verify["access_logs_in_event"] >= ok200))
    print("\nCriterio de cédula:\n")
    for text, ok in checks:
        print(f"- {'✔' if ok else '✘'} {text}")
    if not (verify and verify.get("access_logs_in_event") is not None):
        print(f"- ? base: falta la línea LOAD_VERIFY (`run_phase4.sh verify`): access_logs_in_event >= {ok200} escaneos 200")
    bad = [t for t, ok in checks if not ok]
    print(f"\nCriterio cedula → {'CUMPLE' if not bad else 'NO CUMPLE'}" + ("" if verify else " (a falta de la verificación de la base)"))
    return 1 if bad else 0


def forms_criteria(merged: dict, users: dict, errors: dict, gens: list, verify) -> int:
    """Imprime el criterio de formularios y devuelve 0 (cumple) o 1."""
    checks = []                                                      # (texto, cumple)
    st = merged.get("GET state")
    if st:
        p95, p99 = percentile(st["hist"], .95), percentile(st["hist"], .99)
        checks.append((f"state p95 {p95} ms < {STATE_P95_MS} y p99 {p99} ms < {STATE_P99_MS}", p95 < STATE_P95_MS and p99 < STATE_P99_MS))
    total = sum(v["requests"] for v in users.values())
    good = sum(v["requests"] for k, v in users.items() if k in ("inscrito", "cupo lleno"))
    if total:
        pct = 100 * good / total
        checks.append((f"{pct:.1f} % de los usuarios que envían terminan «inscrito» o «cupo lleno» (mínimo {USER_OK_PCT} %; {total - good} sin terminar bien)", pct >= USER_OK_PCT))
    ins = users.get("inscrito")
    if ins:
        t95 = percentile(ins["hist"], .95) / 1000
        checks.append((f"p95 del tiempo total de quien se inscribe {t95:.1f} s < {USER_P95_S} s (meta {USER_P95_GOAL_S} s: {'alcanzada' if t95 < USER_P95_GOAL_S else 'aún no'})", t95 < USER_P95_S))
    checks += infra_checks(merged, errors, all_done=total == good)
    saturated = [t for t, g in gens if g["cpu_pct"] > 85 or g["lag_p95_ms"] > 200]
    checks.append((f"generadores saturados: {saturated or 'ninguno'}", not saturated))
    if verify:
        expected = min(verify.get("capacity") or total, total)
        clean_run = total == good
        checks.append((f"base: inscripciones confirmadas {verify['confirmed_submissions']} = min(capacidad {verify.get('capacity')}, usuarios únicos que envían {total}) = {expected}"
                       + ("" if clean_run else " (hay usuarios sin terminar bien: solo se exige que no pase de ese valor)"),
                       verify["confirmed_submissions"] == expected if clean_run else verify["confirmed_submissions"] <= expected))
        checks.append((f"base: sobreventas {verify['oversold']}, cédulas repetidas {verify['duplicate_persons']}, `sid` repetidas {verify['duplicate_sids']} (0 esperadas)",
                       verify["oversold"] == 0 and verify["duplicate_persons"] == 0 and verify["duplicate_sids"] == 0))
    print("\nCriterio de formularios:\n")
    for text, ok in checks:
        print(f"- {'✔' if ok else '✘'} {text}")
    if not verify:
        print(f"- ? base: falta la línea LOAD_VERIFY (`run_phase4.sh verify`): confirmadas = min(capacidad, {total} usuarios únicos que envían), 0 sobreventas, 0 duplicados")
    bad = [t for t, ok in checks if not ok]
    print(f"\nCriterio forms → {'CUMPLE' if not bad else 'NO CUMPLE'}" + ("" if verify else " (a falta de la verificación de la base)"))
    print("La contrapresión («ocupado» con reintento) se reporta aparte y no cuenta como fallo.")
    return 1 if bad else 0


def main(paths: list) -> int:
    by_scenario = {}
    for p in paths:
        for r in parse(p):
            by_scenario.setdefault(r["scenario"], []).append(r)
    verify = next((v for v in (parse_verify(p) for p in paths) if v), None)
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
            if name.startswith(USER_PREFIX) or BACKPRESSURE in name:
                continue                                     # van en sus propias tablas (abajo)
            print(f"| {name} | {m['requests']} | {m['failures']} | {percentile(m['hist'], .5)} | {percentile(m['hist'], .95)} | {percentile(m['hist'], .99)} | {m['max_ms']:.0f} |")
        back = {k: v for k, v in merged.items() if BACKPRESSURE in k}
        if back:
            print("\nContrapresión (respuestas «ocupado» con reintento: 502/503/504 y el 429 de infraestructura; NO son fallos, el usuario reintenta con la misma `sid`):\n")
            print("| Intento | Respuestas | % de los intentos de esa petición |\n|---|---:|---:|")
            for name, m in sorted(back.items()):
                base = name.split(" (contrapresión")[0]
                attempts = sum(v["requests"] for k, v in merged.items() if k.split(" (contrapresión")[0] == base and not k.startswith(USER_PREFIX))
                print(f"| {name} | {m['requests']} | {100 * m['requests'] / max(attempts, 1):.0f} % |")
        users = {k[len(USER_PREFIX):]: v for k, v in merged.items() if k.startswith(USER_PREFIX)}
        gens = [(r["task"], r["generator"]) for r in results if r.get("generator")]
        if users:
            total = sum(v["requests"] for v in users.values())
            print(f"\nResultado FINAL por usuario virtual que envía ({total} usuarios; tiempo desde su primer intento hasta el resultado, con todos los reintentos):\n")
            print("| Resultado | Usuarios | % | p50 s | p95 s | máx s |\n|---|---:|---:|---:|---:|---:|")
            for name, m in sorted(users.items(), key=lambda kv: -kv[1]["requests"]):
                print(f"| {name} | {m['requests']} | {100 * m['requests'] / max(total, 1):.1f} | {percentile(m['hist'], .5) / 1000:.1f} | {percentile(m['hist'], .95) / 1000:.1f} | {m['max_ms'] / 1000:.1f} |")
        gens = [(r["task"], r.get("generator")) for r in results if r.get("generator")]
        if gens:
            print("\nGenerador (si la CPU pasa de ~85 % o el retraso p95 de ~200 ms, la latencia medida incluye la espera del PROPIO generador y no vale como latencia del servidor):")
            for task, g in sorted(gens):
                flag = "  ⚠ SATURADO" if g["cpu_pct"] > 85 or g["lag_p95_ms"] > 200 else ""
                print(f"- tarea {task}: CPU {g['cpu_pct']} %, retraso del bucle p95 {g['lag_p95_ms']} ms, máx {g['lag_max_ms']} ms{flag}")
        if errors:
            print("\nFallos por motivo:\n" + "\n".join(f"- {v} × {k}" for k, v in sorted(errors.items(), key=lambda kv: -kv[1])[:10]))
        if scenario == "forms":
            verdict |= forms_criteria(merged, users, errors, gens, verify)
            continue
        if scenario == "cedula":
            verdict |= cedula_criteria(merged, users, errors, gens, verify)
            continue
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
