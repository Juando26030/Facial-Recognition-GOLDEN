"""Fase 1.5 (decisión de Juan David, 5-nov-2026): lo que ven las personas (formulario público, consentimiento, escarapela digital, certificado, páginas legales, pantalla
del proyector) y la impresión NO se rediseñan ni se tocan por ahora — hay un formulario activo. Esta prueba guarda la huella (SHA-256) de esos archivos: si alguien los cambia,
falla. Para cambiarlos a propósito (con orden expresa de Juan David) se actualiza la huella en este archivo y se explica en el PR."""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 9-nov-2026 (cierre Fase 4): form_public.html, legal_base.html y form-render.js cambiaron A PROPÓSITO (compromiso digital: ficha, secciones, avisos); hashes renovados.
# 9-nov-2026 (revisión F5-9): digital_badge.html cambió A PROPÓSITO en la Fase 8 (QR dinámico, Wallet y enlace de contactos, orden de Juan David); y por ORDEN EXPRESA de
# Juan David todas las páginas llevan el ícono de Golden en la pestaña (solo se agregaron las líneas <link rel="icon">). Hashes renovados.
# 9-nov-2026, orden expresa de Juan David: estado de carga en botones («en ningún botón se pueda pensar que no funcionó»). form_public.html («Continuar» del código de
# acceso y de la identificación), aceptar.html («Continuar», aceptar/no aceptar, enviar selfie) y digital_badge.html (Google Wallet) solo ganaron aria-busy + una rueda en
# el botón pulsado; sin cambiar textos, validaciones ni flujo. El certificado y la ruleta ya mostraban «Buscando…»/«Girando…»: no se tocaron. Hashes renovados.
FROZEN = {
    "templates/form_public.html": "2fe3e8bd0da2dae66341232eaa5211900793a9ee4dfb933689fe866ee4421172",
    "templates/aceptar.html": "a5331fff1d3c6a4056db7474136ec3133fdd0bf8620875664b489ca402af567d",
    "templates/aceptar_no_disponible.html": "a8de359cc787156269fb23be9d91729a0e1cf977168d1a4c7b5ee2131b2b01e4",
    "templates/digital_badge.html": "24f47b02a31691c101c058524013fdf0e29d27e21c3af3ca22da216db6b8680b",
    "templates/certificate_public.html": "68e316e797bac84ff13d95d6e05b14f19fb8b210d1c0c6d21f9f03a78b787718",
    "templates/legal_base.html": "3b9bd1eb2fabec5d3631ec3e8fa1f1fc384cadbb9d79e3099f8076b3c2dfc0b0",
    "templates/legal_privacidad.html": "04482353406d3bbe8df4d3929bb0e0c774d65656de3db0662608740a62b9f4a4",
    "templates/legal_privacidad_v11.html": "4367004251dd59ae1e27c9b27bcfbb7038e9f7ccce156a0ee490af5bc6e12076",
    "templates/legal_reembolsos.html": "15bea23df9f8ed5e9b609d54ff9ae840ada3d3d5279696fadee263b9348dcd96",
    "templates/legal_terminos.html": "430e4be0d440b56ef7522a25aacd13c8ba01eac4d5565cf4d35e013fc6d0a85d",
    "templates/roulette_display.html": "b66d1a9f3f767b7b46b091ba0f6ea90f3db90b04c88433f23eaa4353fb7385ee",
    "templates/badge_print.html": "9e48e3062df12c53bb46c747f49a21ba0168af4f2343928f48b64c7530c49655",
    # 6-nov-2026, ORDEN EXPRESA de Juan David: sin asteriscos de cara al público; «(opcional)» en lo no obligatorio y aviso «Tienes que llenar este campo».
    "static/js/form-render.js": "44ab6b5b75382e6284642060169ac2c7ee0ea6916e587b0e90e856a475950ba3",
    "static/js/rich-text.js": "98faba6a4a983a5d0a9cd0946236e4816b40ed29b4bb23931b22874cf5d57405",
    "static/js/direct-upload.js": "9b22353dca8650e6b924aca2114aeba2eec713b875c8a996631affd5e3f500f3",
    "static/js/fonts-propias.js": "ba6dfca9f9f9dda41587f0fb04d292221b45ca0f9ba858faeb90cdec197a0498",
    "static/css/fonts-propias.css": "ac7d385e4523d16f1e096040af3ec024beb81e283f04805597cd945821ec93f0",
    "static/js/cookie-notice.js": "3ba161fa3e997046272fdba4dbcab23582579669995ebc3a64bdd281cab33990",
    "static/js/badge-render.js": "56715ba99b3c11ba995bb43e40e66f2d8c15698358e858513a95fe2908a374e5",
    "static/js/roulette-render.js": "73ae0ed6f3ee2b34c9265eba50cb04df1e9906df7b1a30094d0b3cc36d58abe4",
    "static/js/photo-capture.js": "d2d938ab04bba511f06b20981fb12e2a94321239e047a961d81eb41b88b55da4",
    "static/css/agrandir.css": "a3ca46e1a8b678f2f3a55b4663f529d6c975e81c9dc6bf5313b2c0c09ea4384d",
}


def _sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def test_public_and_print_files_are_unchanged():
    changed = [rel for rel, digest in FROZEN.items() if _sha(rel) != digest]
    assert not changed, f"Archivos congelados que cambiaron (la Fase 1.5 no los toca; ver docs/ux/FASE_1_5_PLAN.md §0): {changed}"


def test_public_pages_do_not_load_the_admin_design_system():
    # lo global (modo touch, componentes .gw-*, style.css) no debe alcanzar a las páginas públicas
    for rel in ("templates/form_public.html", "templates/aceptar.html", "templates/digital_badge.html", "templates/certificate_public.html", "templates/roulette_display.html"):
        html = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"design-system\.css|css/style\.css|_gw_head|touch-detect|gw-ui\.js", html), rel
