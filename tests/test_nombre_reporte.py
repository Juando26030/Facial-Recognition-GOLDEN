"""Nombre del archivo del reporte: «<evento> - <código> - <tipo>.xlsx» (orden del 24-oct-2026)."""
from types import SimpleNamespace
from urllib.parse import unquote

from app import heavy
from tests.test_carga_por_pasos import login


def _ev(name, code):
    return SimpleNamespace(name=name, event_code=code)


def test_the_name_is_event_code_and_report_type():
    assert heavy.event_report_filename(_ev("Congreso Cundi 2026", "23306"), "Reporte final") == "Congreso Cundi 2026 - 23306 - Reporte final.xlsx"


def test_accents_and_enye_survive_in_utf8_and_have_an_ascii_fallback():
    name = heavy.event_report_filename(_ev("Año Nuevo Ñandú Cámara", "7"), "Reporte final")
    cd = heavy.content_disposition(name)
    assert name == "Año Nuevo Ñandú Cámara - 7 - Reporte final.xlsx"
    assert cd.startswith('attachment; filename="Ano Nuevo Nandu Camara - 7 - Reporte final.xlsx"; filename*=UTF-8\'\'')
    assert unquote(cd.split("filename*=UTF-8''")[1]) == name
    cd.encode("ascii")                                                              # la cabecera completa es ASCII puro


def test_invalid_characters_are_removed_and_spaces_collapsed():
    name = heavy.event_report_filename(_ev('Feria / "Sur" : <Norte>*?  |\\ ', "A1"), "Reporte final")
    assert name == "Feria Sur Norte - A1 - Reporte final.xlsx"
    assert not any(c in name for c in '/\\:*?"<>|')


def test_a_very_long_name_is_cut_but_code_and_type_stay_whole():
    name = heavy.event_report_filename(_ev("X" * 300, "23306"), "Reporte final")
    assert name == "X" * 100 + " - 23306 - Reporte final.xlsx"


def test_an_event_without_code_leaves_no_loose_dashes():
    assert heavy.event_report_filename(_ev("Congreso", ""), "Reporte final") == "Congreso - Reporte final.xlsx"
    assert heavy.event_report_filename(_ev("Congreso", None), "Reporte final") == "Congreso - Reporte final.xlsx"
    assert heavy.event_report_filename(_ev("", "23306"), "Reporte final") == "23306 - Reporte final.xlsx"


def test_the_direct_download_endpoint_uses_the_event_name(client, factory):
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    login(client, "coord1")
    r = client.get(f"/api/report?event_id={ev.id}")
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert unquote(cd.split("filename*=UTF-8''")[1]) == heavy.event_report_filename(ev, "Reporte final")
