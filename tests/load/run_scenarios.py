"""Corre los escenarios de carga uno por uno con Locust (sin interfaz) y resume los resultados en una tabla Markdown.

    python tests/load/run_scenarios.py --label antes --spawn                 # arranca (y apaga) el servidor por cada escenario
    python tests/load/run_scenarios.py --label despues --spawn --workers 3   # igual, con 3 procesos
    python tests/load/run_scenarios.py --label prueba --host http://127.0.0.1:5002 --only a,b   # contra un servidor ya levantado

Con `--spawn` cada escenario arranca su propio servidor (uvicorn, contra la base `golden_load`) y lo apaga al terminar: así un
escenario que deje el servidor colgado no contamina a los siguientes, y se ve cuántos procesos/hilos se usaron.
Los CSV y la tabla se guardan FUERA del repo (por defecto C:\\JDRJ\\Golden\\perf_results, variable LOAD_RESULTS_DIR): pueden contener rutas o nombres de fotos.
Solo contra una base/servidor LOCAL o de staging. Nunca producción. Usa 127.0.0.1 y no «localhost» (en Windows «localhost» prueba primero IPv6 y cada intento tarda ~2 s).
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit, urlunsplit

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# clave: (clase del locustfile, usuarios virtuales, usuarios nuevos por segundo, descripción)
SCENARIOS = {
    "a": ("FormUser", 300, 100, "(a) apertura + envío de formulario, 300 usuarios (~150 envíos/s)"),
    "b": ("CedulaScanner", 200, 50, "(b) escaneo por cédula, 200 estaciones (~57/s)"),
    "c": ("FaceScanner", 20, 10, "(c) escaneo facial, 20 estaciones (~6/s)"),
    "d": ("Mixed", 200, 50, "(d) mezcla 60 % formulario / 30 % cédula / 10 % facial, 200 usuarios"),
    "e": ("DirectoryViewer", 20, 10, "(e) directorio en vivo de 8.000 personas, 20 pantallas"),
}


def load_db_url() -> str:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    cfg = json.load(open(os.path.join(HERE, ".load_env.json"), encoding="utf8"))
    base = os.getenv("LOAD_DATABASE_URL") or os.environ["DATABASE_URL"]
    url = urlunsplit(urlsplit(base)._replace(path="/" + cfg["database"]))
    if (urlsplit(url).hostname or "").lower() not in ("localhost", "127.0.0.1", "::1"):
        sys.exit("La base de carga debe ser local.")
    return url


def spawn_server(port: int, workers: int, extra_env: dict, app_dir: str = ROOT):
    env = {**os.environ, "DATABASE_URL": load_db_url(), "ENVIRONMENT": "development", "PYTHONWARNINGS": "ignore", **extra_env}
    if workers > 1:
        env["WEB_CONCURRENCY"] = str(workers)
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--workers", str(workers), "--log-level", "warning"]
    proc = subprocess.Popen(cmd, cwd=app_dir, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        if proc.poll() is not None:                # el proceso murió (p. ej. el puerto seguía ocupado): no dar por bueno a otro servidor
            sys.exit("El servidor de prueba terminó al arrancar (¿puerto ocupado?).")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/login", timeout=2).read()
            return proc
        except Exception:  # noqa: BLE001
            time.sleep(1)
    proc.kill()
    sys.exit("El servidor de prueba no arrancó.")


def stop_server(proc) -> None:
    if not proc:
        return
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) if os.name == "nt" else proc.kill()


def run(key: str, args, outdir: str):
    cls, users, rate, desc = SCENARIOS[key]
    prefix = os.path.join(outdir, f"{args.label}_{key}")
    port = args.port + list(SCENARIOS).index(key)          # un puerto distinto por escenario: nunca se mezcla con un servidor que se está apagando
    proc = spawn_server(port, args.workers, {}, args.app_dir or ROOT) if args.spawn else None
    host = f"http://127.0.0.1:{port}" if args.spawn else args.host
    try:
        cmd = [sys.executable, "-m", "locust", "-f", os.path.join(HERE, "locustfile.py"), cls, "--headless", "--host", host,
               "-u", str(max(1, int(users * args.scale))), "-r", str(rate), "-t", f"{args.duration}s", "--csv", prefix, "--only-summary"]
        subprocess.run(cmd, cwd=ROOT, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        stop_server(proc)
    rows = []
    try:
        with open(prefix + "_stats.csv", encoding="utf8", errors="replace") as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        pass
    return desc, rows


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="corrida")
    ap.add_argument("--host", default="http://127.0.0.1:5002")
    ap.add_argument("--spawn", action="store_true", help="arranca y apaga el servidor por cada escenario")
    ap.add_argument("--workers", type=int, default=1, help="procesos del servidor (solo con --spawn)")
    ap.add_argument("--port", type=int, default=5002)
    ap.add_argument("--app-dir", default="", help="carpeta con OTRA copia del código (p. ej. un `git worktree` de main) para medir la línea base con el mismo método")
    ap.add_argument("--duration", type=int, default=45, help="segundos por escenario")
    ap.add_argument("--only", default="a,b,c,d,e")
    ap.add_argument("--scale", type=float, default=1.0, help="multiplica los usuarios virtuales")
    args = ap.parse_args()
    if not args.spawn and not any(h in args.host for h in ("localhost", "127.0.0.1", "staging")):
        sys.exit("Por seguridad solo se permite localhost, 127.0.0.1 o un host con «staging» en el nombre.")
    outdir = os.getenv("LOAD_RESULTS_DIR", r"C:\JDRJ\Golden\perf_results")
    os.makedirs(outdir, exist_ok=True)
    lines = [f"### {args.label}  (procesos={args.workers if args.spawn else '?'}, escala={args.scale}, {args.duration}s por escenario)", "",
             "| Escenario | Petición | Solicitudes | Fallos | req/s | p50 ms | p95 ms | p99 ms | máx ms |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for key in [k.strip() for k in args.only.split(",") if k.strip() in SCENARIOS]:
        desc, rows = run(key, args, outdir)
        if not rows:
            lines.append(f"| {desc} | (sin resultados: el servidor no respondió) | | | | | | | |")
        for r in rows:
            if r["Name"] == "Aggregated" or r["Name"].startswith(("GET static", "POST beacon")):
                continue
            lines.append(f"| {desc} | {r['Name']} | {r['Request Count']} | {r['Failure Count']} | {float(r['Requests/s']):.1f} | {r['50%']} | {r['95%']} | {r['99%']} | {float(r['Max Response Time']):.0f} |")
            desc = ""
    text = "\n".join(lines)
    print(text)
    with open(os.path.join(outdir, f"{args.label}.md"), "w", encoding="utf8") as fh:
        fh.write(text + "\n")


if __name__ == "__main__":
    main()
