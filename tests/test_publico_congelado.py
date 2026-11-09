"""Fase 1.5 (decisión de Juan David, 5-nov-2026): lo que ven las personas (formulario público, consentimiento, escarapela digital, certificado, páginas legales, pantalla
del proyector) y la impresión NO se rediseñan ni se tocan por ahora — hay un formulario activo. Esta prueba guarda la huella (SHA-256) de esos archivos: si alguien los cambia,
falla. Para cambiarlos a propósito (con orden expresa de Juan David) se actualiza la huella en este archivo y se explica en el PR."""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 9-nov-2026 (cierre Fase 4): form_public.html, legal_base.html y form-render.js cambiaron A PROPÓSITO (compromiso digital: ficha, secciones, avisos); hashes renovados.
FROZEN = {
    "templates/form_public.html": "ea04c1a55cf9734369cafac1be9e4619351c7069c461a95c803d145fdce79fd9",
    "templates/aceptar.html": "4b17b85c8ae07ed355cdd86d048beeef5bf98ad5d3c94620e57b20a6e6c34cad",
    "templates/aceptar_no_disponible.html": "c8f76e761f2d68d59898e2843a7582afe1204f3cc3988771f0ad4350cfd96e2c",
    "templates/digital_badge.html": "f6490dc2cd932d13aa45a725e36fd80cafbd831c56b796a21b9a841a19f6062a",
    "templates/certificate_public.html": "11e54fd3e40972b7faec3bbd0fe2d1822fe1f7a258ca4f33e5f51f1d3fb9bf80",
    "templates/legal_base.html": "409d89e0a5cfb16c8a7f0b8eb522a920f2e73b75584d4e64dc47a8dfa48d5529",
    "templates/legal_privacidad.html": "04482353406d3bbe8df4d3929bb0e0c774d65656de3db0662608740a62b9f4a4",
    "templates/legal_privacidad_v11.html": "4367004251dd59ae1e27c9b27bcfbb7038e9f7ccce156a0ee490af5bc6e12076",
    "templates/legal_reembolsos.html": "15bea23df9f8ed5e9b609d54ff9ae840ada3d3d5279696fadee263b9348dcd96",
    "templates/legal_terminos.html": "430e4be0d440b56ef7522a25aacd13c8ba01eac4d5565cf4d35e013fc6d0a85d",
    "templates/roulette_display.html": "434b88d72802742d43742a11dac347a273bdd4f0c687d4bb71b91264276b3917",
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
