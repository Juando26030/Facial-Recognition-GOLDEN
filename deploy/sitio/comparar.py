#!/usr/bin/env python3
"""Compara DOS compilaciones del sitio web (p. ej. el original y el parchado) para demostrar que se ven igual.

Sirve cada carpeta dist/ en un puerto local, abre las mismas páginas con Chromium (Playwright) en varios anchos, toma una captura de
página completa de cada una y las compara píxel a píxel. También compara el texto visible. No toca internet ni la nube.

    python3 deploy/sitio/comparar.py --a <dist original> --b <dist parchado> --salida build/sitio/comparacion
    python3 deploy/sitio/comparar.py --url-a https://vista-previa... --url-b http://127.0.0.1:8000   # dos direcciones ya servidas

Sale con 0 si todo es «IDÉNTICO» (dentro de la tolerancia) y con 1 si alguna página difiere; deja en --salida las capturas, una imagen
de diferencias por caso y resumen.json. Requisitos: pip install playwright pillow && python3 -m playwright install chromium.

Para que la comparación sea justa se congela todo lo que se mueve: «reducir movimiento», sin animaciones ni transiciones, y los <canvas>
(escenas 3D con posiciones al azar) se ocultan salvo --con-canvas. Lo que el parche oculta a propósito (sección «Lo que hemos hecho»:
inicio.json → eventos.publicar) SÍ cambia la portada: para probar «idéntico» compile el parchado con eventos.publicar=true.
"""
import argparse
import functools
import http.server
import json
import os
import sys
import threading

ANCHOS = [320, 390, 768, 1024, 1280, 1440, 1920, 2560, 3440]
RUTAS = ["/", "/cotizar", "/terminos"]
CONGELAR = """
*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; scroll-behavior: auto !important; }
html { scroll-behavior: auto !important; }
[data-reveal], .entra, .linea__in, .hero__emblema img { opacity: 1 !important; transform: none !important; translate: none !important; }
"""
SIN_CANVAS = "canvas { visibility: hidden !important; }"


class Silencioso(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_head(self):   # /cotizar → /cotizar/index.html (lo que hace Firebase Hosting con cleanUrls)
        ruta = self.translate_path(self.path.split("?")[0])
        if not os.path.exists(ruta) and os.path.exists(ruta + ".html"):
            self.path = self.path.split("?")[0] + ".html"
        return super().send_head()


def servir(carpeta):
    if not os.path.isfile(os.path.join(carpeta, "index.html")):
        sys.exit(f"{carpeta} no parece una carpeta dist/ (no tiene index.html)")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Silencioso, directory=carpeta))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def capturar(page, url, ancho, alto, destino, con_canvas):
    page.set_viewport_size({"width": ancho, "height": alto})
    page.goto(url, wait_until="networkidle")
    page.add_style_tag(content=CONGELAR + ("" if con_canvas else SIN_CANVAS))
    page.evaluate("document.fonts && document.fonts.ready")
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")   # dispara lo que aparece al bajar
    page.wait_for_timeout(250)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(250)
    page.screenshot(path=destino, full_page=True)
    texto = page.evaluate("document.body.innerText")
    desborde = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 1")
    return " ".join(texto.split()), desborde


def diferencia(ruta_a, ruta_b, ruta_dif, umbral):
    from PIL import Image, ImageChops
    a, b = Image.open(ruta_a).convert("RGB"), Image.open(ruta_b).convert("RGB")
    if a.size != b.size:
        return {"igual": False, "motivo": f"tamaños distintos: {a.size} y {b.size}", "pct": 100.0}
    dif = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > umbral else 0)
    distintos = sum(dif.histogram()[255:])
    pct = 100.0 * distintos / (a.size[0] * a.size[1])
    if distintos:
        ImageChops.blend(a.convert("L").convert("RGB"), Image.merge("RGB", (dif, Image.new("L", a.size), Image.new("L", a.size))), 0.6).save(ruta_dif)
    return {"igual": distintos == 0, "pct": round(pct, 4), "caja": dif.getbbox()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a"), ap.add_argument("--b")
    ap.add_argument("--url-a"), ap.add_argument("--url-b")
    ap.add_argument("--salida", default="build/sitio/comparacion")
    ap.add_argument("--rutas", nargs="*", default=RUTAS)
    ap.add_argument("--anchos", nargs="*", type=int, default=ANCHOS)
    ap.add_argument("--alto", type=int, default=900)
    ap.add_argument("--umbral", type=int, default=8, help="diferencia de color (0-255) que cuenta como píxel distinto")
    ap.add_argument("--tolerancia", type=float, default=0.0, help="%% de píxeles distintos que aún se acepta como idéntico")
    ap.add_argument("--con-canvas", action="store_true", help="no ocultar los <canvas> (las escenas 3D cambian en cada carga)")
    o = ap.parse_args()
    from playwright.sync_api import sync_playwright

    servidores = []
    url_a, url_b = o.url_a, o.url_b
    if not url_a:
        s, url_a = servir(o.a or sys.exit("Falta --a <dist> o --url-a")); servidores.append(s)
    if not url_b:
        s, url_b = servir(o.b or sys.exit("Falta --b <dist> o --url-b")); servidores.append(s)
    os.makedirs(o.salida, exist_ok=True)
    casos, malos = [], 0
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(reduced_motion="reduce", device_scale_factor=1, locale="es-CO")
        page = ctx.new_page()
        for ruta in o.rutas:
            for ancho in o.anchos:
                nombre = (ruta.strip("/").replace("/", "_") or "inicio") + f"_{ancho}"
                fa, fb, fd = (os.path.join(o.salida, f"{nombre}_{x}.png") for x in ("a", "b", "dif"))
                ta, da = capturar(page, url_a.rstrip("/") + ruta, ancho, o.alto, fa, o.con_canvas)
                tb, db = capturar(page, url_b.rstrip("/") + ruta, ancho, o.alto, fb, o.con_canvas)
                r = diferencia(fa, fb, fd, o.umbral)
                r.update(ruta=ruta, ancho=ancho, texto_igual=ta == tb, desborde_a=da, desborde_b=db)
                ok = (r["igual"] or r["pct"] <= o.tolerancia) and r["texto_igual"] and not db
                r["veredicto"] = "IDÉNTICO" if ok else "DISTINTO"
                malos += 0 if ok else 1
                casos.append(r)
                extra = "" if r["texto_igual"] else " · TEXTO distinto"
                extra += " · DESBORDE horizontal en B" if db else ""
                print(f"{r['veredicto']:9} {ruta:22} {ancho:5} px  {r['pct']:.4f} % de píxeles{extra}")
        nav.close()
    for s in servidores:
        s.shutdown()
    with open(os.path.join(o.salida, "resumen.json"), "w", encoding="utf8") as fh:
        json.dump({"a": url_a, "b": url_b, "casos": casos}, fh, ensure_ascii=False, indent=2)
    print(f"\n{'TODO IDÉNTICO' if not malos else f'{malos} caso(s) DISTINTOS'} · {len(casos)} comparaciones · detalle en {o.salida}")
    sys.exit(1 if malos else 0)


if __name__ == "__main__":
    main()
