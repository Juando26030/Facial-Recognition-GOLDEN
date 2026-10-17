"""Nada de terceros en las páginas: ni fuentes ni el script del QR se piden fuera de nuestro servidor (app de biometría: la IP de las personas no se le entrega a nadie)."""
import pathlib
import re

SCRIPT_HOSTS_NO_QR = re.compile(r"https?://[^\"'\s)]*qrcode[^\"'\s)]*", re.I)


def _files():
    for root in ("templates", "static/css", "static/js"):
        for f in pathlib.Path(root).rglob("*"):
            if f.suffix in (".html", ".css", ".js"):
                yield f, f.read_text(encoding="utf-8", errors="ignore")


def test_the_qr_script_comes_from_our_own_static_files_and_never_from_a_cdn(client):
    users = [f.as_posix() for f, text in _files() if "qrcode-generator-1.4.4.min.js" in text]
    assert len(users) >= 6, users                                                                    # las 6 pantallas que dibujan QR
    assert [f.as_posix() for f, text in _files() if SCRIPT_HOSTS_NO_QR.search(text)] == []
    r = client.get("/static/vendor/qrcode-generator-1.4.4.min.js")
    assert r.status_code == 200 and "qrcode" in r.text[:60]
