"""24-nov-2026: cédula leída a medias → cédulas parecidas (app/cedula_near.py). Pura: sin base de datos."""
import re
from pathlib import Path

from app import cedula_near as cn


def test_un_error_de_lectura_de_cada_tipo():
    v = set(cn.variants("1020457789"))
    assert "1020457788" in v              # un dígito mal leído
    assert "1020547789" in v              # dos vecinos intercambiados
    assert "102045789" in v               # sobraba un dígito (un brillo leído como número)
    assert "10204577789" in v             # faltaba un dígito (el brillo lo tapó)
    assert "1020457789" not in v          # la lectura misma no es «parecida»
    assert all(not x.startswith("0") for x in v)
    assert len(v) < 300                   # búsqueda por igualdad sobre el índice, nunca un recorrido de personas


def test_muy_pocos_digitos_no_ofrece_nada_y_limpia_basura():
    assert cn.variants("1234") == []
    assert cn.variants(None) == []
    assert cn.clean("1.020.457.789<<") == "1020457789"


def test_el_endpoint_nunca_acredita_y_no_deja_la_cedula_en_registros():
    src = Path("app/routers/cedula.py").read_text(encoding="utf-8")
    body = src[src.index('def cedula_near_candidates'):]
    assert 'require_role("digitador")' in src[src.index('"/events/{event_id}/cedula-near"'):]
    assert "get_event_for_staff(" in body
    assert not re.search(r"AccessLog|db\.add\(|db\.commit\(|log\.(info|warning|error)\(", body)
