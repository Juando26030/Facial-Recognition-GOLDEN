"""Vigilante de backups: comprueba que las copias EXTERNAS existan, estén frescas y no estén raras, y avisa por correo si no.

Sin esto un backup que falla en silencio se descubre el día que hace falta. Corre por cron (cada hora, minuto 35), con el mismo entorno del backup:

    35 * * * * cd /home/juando02603/Facial-Recognition && GCS_BUCKET=gs://... GCS_DATA_BUCKET=gs://... venv/bin/python scripts/check_backups.py >> /home/juando02603/backups/check.log 2>&1

Comprueba: (1) el volcado más reciente de la base en el bucket tiene menos de DB_MAX_AGE_H horas (3); (2) no pesa menos de la mitad
de lo normal (señal de un volcado vacío o cortado); (3) la copia del .env en el bucket de archivos es de hoy o ayer; (4) el disco de la VM
no está casi lleno. Avisa a ALERT_EMAIL (por Graph/SMTP, como el resto de correos del sistema), como máximo una vez cada 6 h por problema, y
manda un «recuperado» cuando todo vuelve a la normalidad. `--test` solo envía un correo de prueba para confirmar que el aviso llega.
Sale con código 1 si hay algún problema.
"""
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.getcwd())

from dotenv import load_dotenv

load_dotenv()

from app.mailer import send_mail  # noqa: E402

GCS_BUCKET = os.getenv("GCS_BUCKET", "").rstrip("/")
GCS_DATA_BUCKET = os.getenv("GCS_DATA_BUCKET", "").rstrip("/")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "").strip()
DB_MAX_AGE_H = float(os.getenv("DB_MAX_AGE_H", "3"))
ENV_MAX_AGE_H = float(os.getenv("ENV_MAX_AGE_H", "30"))
REALERT_H = float(os.getenv("REALERT_H", "6"))
STATE = os.path.join(os.getenv("BACKUP_DIR", os.path.expanduser("~/backups")), ".check_state.json")
LINE = re.compile(r"^\s*(\d+)\s+(\d{4}-\d\d-\d\dT[\d:.]+Z)\s+(gs://\S+)\s*$")


def listing(url: str, recursive: bool = True):
    cmd = ["gcloud", "storage", "ls", "--long"] + (["--recursive"] if recursive else []) + [url]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[-300:] or "gcloud falló")
    rows = []
    for line in out.stdout.splitlines():
        m = LINE.match(line)
        if m:
            rows.append((datetime.fromisoformat(m.group(2).replace("Z", "+00:00")), int(m.group(1)), m.group(3)))
    return sorted(rows)


def age_h(ts: datetime) -> float:
    return (datetime.now(timezone.utc) - ts).total_seconds() / 3600


def problems() -> dict:
    found = {}
    if not GCS_BUCKET:
        found["config-db"] = "GCS_BUCKET no está definido: nadie está copiando la base fuera de la VM."
    else:
        try:
            dumps = [r for r in listing(f"{GCS_BUCKET}/db/") if r[2].endswith(".sql.gz")]
            if not dumps:
                found["db-none"] = f"No hay ningún volcado de la base en {GCS_BUCKET}/db/."
            else:
                last = dumps[-1]
                if age_h(last[0]) > DB_MAX_AGE_H:
                    found["db-old"] = f"El último volcado de la base tiene {age_h(last[0]):.1f} h ({last[2]}); debería tener menos de {DB_MAX_AGE_H:g} h."
                sizes = [r[1] for r in dumps[-24:-1]]
                if len(sizes) >= 5 and last[1] < 0.5 * statistics.median(sizes):
                    found["db-small"] = f"El último volcado pesa {last[1]} bytes y lo normal es ~{int(statistics.median(sizes))}: puede estar vacío o cortado ({last[2]})."
        except Exception as e:  # noqa: BLE001
            found["db-check"] = f"No se pudo revisar el bucket de la base: {e}"
    if GCS_DATA_BUCKET:
        try:
            env = listing(f"{GCS_DATA_BUCKET}/config/.env", recursive=False)
            if not env:
                found["env-none"] = "No hay copia del .env en el bucket de archivos."
            elif age_h(env[-1][0]) > ENV_MAX_AGE_H:
                found["env-old"] = f"La copia del .env/archivos en el bucket tiene {age_h(env[-1][0]):.0f} h: la sincronización nocturna de data/ no está corriendo."
        except Exception as e:  # noqa: BLE001
            found["data-check"] = f"No se pudo revisar el bucket de archivos: {e}"
    else:
        found["config-data"] = "GCS_DATA_BUCKET no está definido: las fotos, firmas y el .env no tienen copia fuera de la VM."
    total, _, free = shutil.disk_usage("/")
    if free / total < 0.15:
        found["disk"] = f"Al disco de la VM le queda {100 * free / total:.0f}% libre."
    return found


def load_state() -> dict:
    try:
        with open(STATE, encoding="utf8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def notify(subject: str, body: str) -> None:
    print(subject, "\n", body)
    if not ALERT_EMAIL:
        print("(ALERT_EMAIL no está definido: el aviso solo queda en este log)")
        return
    result = send_mail(ALERT_EMAIL, subject, body)
    print("aviso:", result["detail"])


def main() -> int:
    if "--test" in sys.argv:
        notify("[Golden] Prueba del aviso de backups", "Si lees esto, los avisos de backups llegan bien a este correo.")
        return 0
    found, state, now = problems(), load_state(), time.time()
    for key in list(state):
        if key not in found:
            del state[key]
            if not state and not found:
                notify("[Golden] Backups: todo volvió a la normalidad", "Las copias externas están al día otra vez.")
    due = {k: v for k, v in found.items() if now - state.get(k, 0) > REALERT_H * 3600}
    if due:
        notify("[Golden] ⚠️ Problema con los backups", "Se detectó lo siguiente:\n\n- " + "\n- ".join(found.values()) + "\n\nRevisa ~/backups/backup.log y ~/backups/cron.log en la VM.")
        for k in due:
            state[k] = now
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf8") as fh:
        json.dump(state, fh)
    print(datetime.now().strftime("%F %T"), "problemas:" if found else "todo bien", "; ".join(found.values()))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
