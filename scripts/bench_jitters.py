"""Mide el costo y la precisión del reconocimiento facial según `num_jitters` (1, 2, 5, 10 y el de referencia 25).

    python scripts/bench_jitters.py                       # carpeta de FOTOS_PRUEBA_DIR (por defecto C:\\JDRJ\\Golden\\fotos_prueba)
    python scripts/bench_jitters.py --dir D:\\otras --max-side 640 --out D:\\resultados

NO cambia nada de la aplicación: solo mide. Sirve para decidir con datos si el escaneo en vivo puede bajar de 10 jitters a 1-2 (ver docs/14_FASE0_RESULTADOS.md).

Qué mide, por cada valor de jitters:
  * tiempo por encoding (mediana y p95, en ms), con la foto reducida al lado mayor indicado (--max-side, por defecto 640 como el navegador del kiosco);
  * desviación frente a la referencia (25 jitters) de la MISMA foto: distancia entre ambos encodings (0 = idéntico; el umbral de match es 0.55);
  * si las fotos vienen agrupadas por persona (una subcarpeta por persona, o nombre `persona_1.jpg`, `persona_2.jpg`...), precisión de verdad:
    de todas las parejas de fotos de la MISMA persona (deberían coincidir) y de DISTINTAS personas (no deberían), cuántas acierta con el umbral 0.55
    (tasa de aciertos y de falsos positivos). Sin ese agrupamiento se informa solo la desviación.

Privacidad: NUNCA imprime ni guarda nombres de archivo, nombres de personas ni encodings: solo cifras agregadas. Los resultados se escriben en --out
(fuera del repo). Las fotos no se copian a ningún lado.
"""
import argparse
import glob
import itertools
import json
import os
import statistics
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
JITTERS = (1, 2, 5, 10)
REFERENCE = 25
THRESHOLD = 0.55


def person_of(path: str, base: str) -> str:
    rel = os.path.relpath(path, base)
    parts = rel.split(os.sep)
    if len(parts) > 1:
        return parts[0]
    stem = os.path.splitext(parts[0])[0]
    for sep in ("_", "-", " "):
        if sep in stem and stem.rsplit(sep, 1)[1].isdigit():
            return stem.rsplit(sep, 1)[0]
    return stem


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.getenv("FOTOS_PRUEBA_DIR", r"C:\JDRJ\Golden\fotos_prueba"))
    ap.add_argument("--max-side", type=int, default=640)
    ap.add_argument("--out", default=os.getenv("LOAD_RESULTS_DIR", r"C:\JDRJ\Golden\perf_results"))
    ap.add_argument("--limit", type=int, default=200, help="máximo de fotos a usar")
    ap.add_argument("--synthetic", action="store_true", help="si no hay carpeta, usa la foto de dominio público de scikit-image (solo mide tiempo)")
    args = ap.parse_args()

    from app.biometrics import BiometricEngine

    paths = sorted(p for ext in ("*.jpg", "*.jpeg", "*.png") for p in glob.glob(os.path.join(args.dir, "**", ext), recursive=True))[: args.limit]
    images, owners = [], []
    if paths:
        for p in paths:
            with open(p, "rb") as fh:
                images.append(BiometricEngine.process_image_stream(fh.read()))
            owners.append(person_of(p, args.dir))
    elif args.synthetic:
        from skimage import data
        images, owners = [data.astronaut()], ["sintetica"]
        print("Sin carpeta de fotos: uso una foto de dominio público de scikit-image. SOLO sirve para el tiempo, no para la precisión.")
    else:
        sys.exit(f"No hay fotos en {args.dir}. Define FOTOS_PRUEBA_DIR o usa --synthetic para medir solo el tiempo.")

    def encode(img, jitters):
        t0 = time.perf_counter()
        enc = BiometricEngine.extract_encoding(img, jitters=jitters, max_side=args.max_side)
        return (np.array(enc) if enc else None), (time.perf_counter() - t0) * 1000

    print(f"{len(images)} fotos, lado mayor {args.max_side}px. Calculando la referencia ({REFERENCE} jitters)...")
    ref = [encode(img, REFERENCE)[0] for img in images]
    usable = [i for i, e in enumerate(ref) if e is not None]
    if not usable:
        sys.exit("Ninguna foto tiene un rostro detectable.")

    persons = sorted(set(owners[i] for i in usable))
    pairs_same, pairs_diff = [], []
    for i, j in itertools.combinations(usable, 2):
        (pairs_same if owners[i] == owners[j] else pairs_diff).append((i, j))
    grouped = bool(pairs_same) and bool(pairs_diff)

    report = {"photos": len(images), "with_face": len(usable), "persons": len(persons) if grouped else None, "max_side": args.max_side, "threshold": THRESHOLD, "rows": []}
    for jit in (*JITTERS, REFERENCE):
        encs, times = {}, []
        for i in usable:
            e, ms = encode(images[i], jit)
            if e is not None:
                encs[i] = e
                times.append(ms)
        dev = [float(np.linalg.norm(encs[i] - ref[i])) for i in encs] if jit != REFERENCE else [0.0]
        row = {"jitters": jit, "ms_median": round(statistics.median(times), 1), "ms_p95": round(float(np.percentile(times, 95)), 1),
               "deviation_mean": round(statistics.mean(dev), 4), "deviation_max": round(max(dev), 4)}
        if grouped:
            same = [np.linalg.norm(encs[i] - encs[j]) for i, j in pairs_same if i in encs and j in encs]
            diff = [np.linalg.norm(encs[i] - encs[j]) for i, j in pairs_diff if i in encs and j in encs]
            row["match_rate_same_person"] = round(sum(d < THRESHOLD for d in same) / len(same), 4) if same else None
            row["false_positive_rate"] = round(sum(d < THRESHOLD for d in diff) / len(diff), 6) if diff else None
            row["same_dist_mean"] = round(float(np.mean(same)), 4) if same else None
            row["diff_dist_min"] = round(float(np.min(diff)), 4) if diff else None
        report["rows"].append(row)

    print()
    head = "| jitters | ms mediana | ms p95 | desviación media vs 25 | desviación máx |" + (" aciertos misma persona | falsos positivos | dist. mínima entre personas distintas |" if grouped else "")
    print(head)
    print("|---:|---:|---:|---:|---:|" + ("---:|---:|---:|" if grouped else ""))
    for r in report["rows"]:
        line = f"| {r['jitters']} | {r['ms_median']} | {r['ms_p95']} | {r['deviation_mean']} | {r['deviation_max']} |"
        if grouped:
            line += f" {r['match_rate_same_person']} | {r['false_positive_rate']} | {r['diff_dist_min']} |"
        print(line)
    if not grouped:
        print("\n(Sin agrupar por persona no se puede medir aciertos ni falsos positivos: pon las fotos en una subcarpeta por persona, o nómbralas persona_1.jpg, persona_2.jpg...)")
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "bench_jitters.json"), "w", encoding="utf8") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nResultados agregados en {os.path.join(args.out, 'bench_jitters.json')} (sin nombres ni encodings).")


if __name__ == "__main__":
    main()
