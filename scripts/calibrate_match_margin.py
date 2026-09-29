"""Calibra MATCH_MARGIN (regla de caso dudoso del reconocimiento, docs/14 §6.3) con fotos de prueba (con consentimiento).

    python scripts/calibrate_match_margin.py --dir C:\\JDRJ\\Golden\\fotos_prueba --out C:\\JDRJ\\Golden\\perf_results
    (en Docker, con la carpeta montada en SOLO LECTURA: ver docs/14 §6.3)

Estructura: una subcarpeta por persona con `registro.*` (se enrola como en producción: 25 jitters, resolución completa) y `kiosko.*`/`kiosco.*` (se escanea como
`app/faces.recognize`: RECOGNITION_JITTERS, rostro más grande, lado mayor 640). NO cambia nada de la aplicación.

Mide, por escaneo (las personas se llaman P01…Pnn por orden; NUNCA se imprime ni se guarda un nombre de carpeta/archivo, un encoding ni una foto):
  * CONJUNTO CERRADO (todos registrados): distancia a la persona correcta vs. la del impostor más cercano; top-1 y top-6 (principal + 5 candidatos); cuántos
    escaneos quedan DUDOSOS con cada margen y, de esos, cuántos habrían sido un error (el mejor no era la persona) o un acierto que se pide verificar.
  * CONJUNTO ABIERTO (el caso de riesgo: alguien NO registrado que se parece a alguien registrado): cada escaneo se repite con la propia persona QUITADA de la
    galería. Cualquier coincidencia (< tolerancia) es un falso positivo; se cuenta cuántos habría evitado cada margen marcándolos DUDOSOS.
Escribe `calibrate_match_margin.json` (agregado y anónimo) en --out y un resumen en Markdown por la salida estándar."""
import argparse
import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TOLERANCE = 0.55
MARGINS = (0.04, 0.06, 0.08)
CURVE = (0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20)          # para ver cómo crece el % de dudosos y cuántos falsos del conjunto abierto se atrapan
EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".avif")


def doubtful(sorted_d, margin: float) -> bool:
    """Igual que app.faces.is_doubtful: los dos primeros distan menos que `margin` (solo se evalúa si el mejor ya está dentro de la tolerancia)."""
    return len(sorted_d) >= 2 and sorted_d[0] < TOLERANCE and (sorted_d[1] - sorted_d[0]) < margin


def load(folder: str):
    """{persona: {"registro": bytes, "kiosko": bytes}} en orden estable; las carpetas sin las dos fotos se descartan."""
    people = {}
    for sub in sorted(d for d in glob.glob(os.path.join(folder, "*")) if os.path.isdir(d)):
        files = sorted(f for f in glob.glob(os.path.join(sub, "*")) if os.path.splitext(f)[1].lower() in EXTENSIONS)
        reg = next((f for f in files if os.path.basename(f).lower().startswith("registro")), None)
        kio = next((f for f in files if os.path.basename(f).lower().startswith(("kiosko", "kiosco"))), None)
        if reg and kio:
            people[len(people)] = {"registro": open(reg, "rb").read(), "kiosko": open(kio, "rb").read()}
    return people


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.getenv("FOTOS_PRUEBA_DIR", r"C:\JDRJ\Golden\fotos_prueba"))
    ap.add_argument("--out", default=os.getenv("LOAD_RESULTS_DIR", r"C:\JDRJ\Golden\perf_results"))
    ap.add_argument("--jitters", type=int, default=int(os.getenv("RECOGNITION_JITTERS", "2")))
    ap.add_argument("--repeat", type=int, default=5, help="veces que se escanea cada foto de kiosco (los jitters son aleatorios: estabiliza las distribuciones)")
    ap.add_argument("--max-side", type=int, default=640)
    args = ap.parse_args()

    from app.biometrics import BiometricEngine

    people = load(args.dir)
    if not people:
        sys.exit(f"No hay carpetas con registro.* y kiosko.* en {args.dir}.")
    gallery, ids = [], []
    for k, p in people.items():
        enc = BiometricEngine.extract_encoding(BiometricEngine.process_image_stream(p["registro"]), is_registration=True)
        if enc:
            gallery.append(enc)
            ids.append(k)
    matrix = np.array(gallery, dtype=np.float32)
    label = {k: f"P{n + 1:02d}" for n, k in enumerate(ids)}
    print(f"{len(ids)} personas enroladas de {len(people)} con las dos fotos; jitters={args.jitters}; {args.repeat} repeticiones por foto de kiosco.\n")

    closed, opened, no_face = [], [], 0
    per_person = {label[k]: {"genuine": [], "impostor": [], "open_best": []} for k in ids}
    for k in ids:
        img = BiometricEngine.process_image_stream(people[k]["kiosko"])
        for _ in range(args.repeat):
            enc = BiometricEngine.extract_encoding(img, jitters=args.jitters, max_side=args.max_side, largest_face=True)
            if enc is None:
                no_face += 1
                continue
            dist = np.linalg.norm(matrix - np.array(enc, dtype=np.float32), axis=1)
            own = ids.index(k)
            order = np.argsort(dist)
            ranked = [(ids[int(i)], float(dist[int(i)])) for i in order[:6]]
            sorted_d = [d for _, d in ranked]
            rank = next((n + 1 for n, (uid, _) in enumerate(ranked) if uid == k), None)      # posición (1-6) de la persona correcta; None = fuera del top 6
            others = np.delete(dist, own)
            closed.append({"top1": ranked[0][0] == k and sorted_d[0] < TOLERANCE, "top6": sorted_d[0] < TOLERANCE and rank is not None, "rank": rank,
                           "matched": sorted_d[0] < TOLERANCE, "wrong": ranked[0][0] != k and sorted_d[0] < TOLERANCE,
                           "sorted": sorted_d, "genuine": float(dist[own]), "impostor": float(others.min())})
            per_person[label[k]]["genuine"].append(float(dist[own]))
            per_person[label[k]]["impostor"].append(float(others.min()))
            o_sorted = np.sort(others)                                                        # conjunto abierto: la persona NO está en la galería
            per_person[label[k]]["open_best"].append(float(o_sorted[0]))
            opened.append({"sorted": [float(x) for x in o_sorted[:6]], "false_match": bool(o_sorted[0] < TOLERANCE)})

    n = len(closed)
    out = {"people": len(ids), "scans": n, "no_face_scans": no_face, "jitters": args.jitters, "tolerance": TOLERANCE,
           "closed": {"top1_pct": round(100 * sum(c["top1"] for c in closed) / n, 1), "top6_pct": round(100 * sum(c["top6"] for c in closed) / n, 1),
                      "wrong_top1_matches": sum(c["wrong"] for c in closed), "no_match": sum(not c["matched"] for c in closed),
                      "margin_min_over_all": round(min(c["impostor"] for c in closed) - max(c["genuine"] for c in closed), 4)},
           "open_set": {"scans": len(opened), "false_matches": sum(o["false_match"] for o in opened)},
           "by_margin": {}, "persons": {}}
    for m in MARGINS:
        cd = [c for c in closed if doubtful(c["sorted"], m)]
        od = [o for o in opened if o["false_match"] and doubtful(o["sorted"], m)]
        out["by_margin"][str(m)] = {
            "closed_doubtful": len(cd), "closed_doubtful_pct": round(100 * len(cd) / n, 1),
            "closed_doubtful_but_correct_top1": sum(c["top1"] for c in cd), "closed_doubtful_and_wrong_top1": sum(c["wrong"] for c in cd),
            "closed_wrong_not_caught": sum(c["wrong"] and not doubtful(c["sorted"], m) for c in closed),
            "open_false_matches_flagged_doubtful": len(od), "open_false_matches_still_auto": sum(o["false_match"] for o in opened) - len(od)}
    gaps_closed = [c["sorted"][1] - c["sorted"][0] for c in closed if len(c["sorted"]) > 1 and c["matched"]]
    gaps_false = [o["sorted"][1] - o["sorted"][0] for o in opened if o["false_match"] and len(o["sorted"]) > 1]
    out["gaps"] = {"closed_matches": {"n": len(gaps_closed), "min": round(min(gaps_closed), 3), "p5": round(float(np.percentile(gaps_closed, 5)), 3), "median": round(float(np.median(gaps_closed)), 3)},
                   "open_false_matches": [round(g, 3) for g in gaps_false],
                   "curve": {str(m): {"closed_doubtful_pct": round(100 * sum(g < m for g in gaps_closed) / len(gaps_closed), 1),
                                      "open_false_flagged": sum(g < m for g in gaps_false), "open_false_total": len(gaps_false)} for m in CURVE}}
    for lab, v in sorted(per_person.items()):
        out["persons"][lab] = {"genuine_max": round(max(v["genuine"]), 3) if v["genuine"] else None, "genuine_mean": round(float(np.mean(v["genuine"])), 3) if v["genuine"] else None,
                               "closest_impostor_min": round(min(v["impostor"]), 3) if v["impostor"] else None,
                               "open_set_best_min": round(min(v["open_best"]), 3) if v["open_best"] else None}
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "calibrate_match_margin.json"), "w", encoding="utf8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)

    c, o = out["closed"], out["open_set"]
    print(f"Conjunto cerrado ({n} escaneos con rostro; {no_face} sin rostro): top-1 {c['top1_pct']} % · top-6 {c['top6_pct']} % · "
          f"falsos positivos como mejor coincidencia: {c['wrong_top1_matches']} · sin coincidencia: {c['no_match']} · margen (mín. impostor − máx. genuina): {c['margin_min_over_all']}")
    print(f"Conjunto abierto (cada escaneo SIN su persona en la galería; {o['scans']} escaneos): coincidencias falsas (< {TOLERANCE}): {o['false_matches']}\n")
    print("| MATCH_MARGIN | dudosos (cerrado) | % | de ellos, acierto a verificar | de ellos, error evitado | errores que pasarían | falsos del abierto marcados dudosos | del abierto que pasarían |")
    print("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for m, v in out["by_margin"].items():
        print(f"| {m} | {v['closed_doubtful']} | {v['closed_doubtful_pct']} | {v['closed_doubtful_but_correct_top1']} | {v['closed_doubtful_and_wrong_top1']} | {v['closed_wrong_not_caught']} | "
              f"{v['open_false_matches_flagged_doubtful']} | {v['open_false_matches_still_auto']} |")
    g = out["gaps"]
    print(f"\nDiferencia entre el mejor y el segundo candidato (conjunto cerrado, {g['closed_matches']['n']} coincidencias): mín. {g['closed_matches']['min']} · p5 {g['closed_matches']['p5']} · "
          f"mediana {g['closed_matches']['median']}. Falsos del conjunto abierto: diferencias {g['open_false_matches']}")
    print("| margen | % dudosos (cerrado) | falsos del abierto atrapados |\n|---:|---:|---:|")
    for m, v in g["curve"].items():
        print(f"| {m} | {v['closed_doubtful_pct']} | {v['open_false_flagged']} de {v['open_false_total']} |")
    print("\n| Persona | genuina máx. | genuina media | impostor más cercano (mín.) | mejor distancia sin ella en la galería (mín.) |")
    print("|---|---:|---:|---:|---:|")
    for lab, v in out["persons"].items():
        print(f"| {lab} | {v['genuine_max']} | {v['genuine_mean']} | {v['closest_impostor_min']} | {v['open_set_best_min']} |")


if __name__ == "__main__":
    main()
