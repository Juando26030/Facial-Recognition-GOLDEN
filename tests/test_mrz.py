"""Cédula nueva (MRZ TD1): corrección por clase de carácter de cada posición, variantes de preparación de la imagen y orquestación del endpoint por orientación y variante. Todo con datos
SINTÉTICOS generados con el estándar ICAO (nunca la cédula de una persona): la foto real que motivó el cambio («COL» leído como «C0L») se probó a mano, fuera del repositorio."""
import io

import numpy as np
import pytest
from mrz.generator.td1 import TD1CodeGenerator
from PIL import Image

from app import mrz_ocr
from app.mrz_parser import _fix_by_position, parse_mrz_td1
from tests.conftest import login

GOOD = str(TD1CodeGenerator("IC", "COL", "123456789", "900101", "F", "350101", "COL", "PEREZ GOMEZ", "ANA MARIA", optional_data1="12345", optional_data2="1234567890")).split("\n")


def test_the_synthetic_sample_is_a_valid_td1():
    r = parse_mrz_td1(*GOOD)
    assert r["valid"] and r["id"] == "1234567890" and r["first_name"] == "ANA MARIA" and r["last_name"] == "PEREZ GOMEZ"


@pytest.mark.parametrize("bad_line,position,wrong", [
    (1, 16, "0"),         # «COL» (nacionalidad) leído «C0L»: el caso real de la foto
    (1, 17, "1"),         # «COL» leído «CO1»
    (1, 1, "O"),          # un 0 del nacimiento leído como letra O
    (1, 10, "D"),         # un 0 del vencimiento leído «D»
    (2, 4, "2"),          # la «Z» del apellido leída como 2
    (2, 20, "1"),         # la «I» del nombre leída como 1
    (2, 7, "0"),          # la «O» del apellido leída como cero
    (0, 3, "0"),          # la «O» del país «COL» de la línea 1 leída como cero
])
def test_ocr_confusions_by_position_are_corrected_and_still_validated(bad_line, position, wrong):
    lines = list(GOOD)
    lines[bad_line] = lines[bad_line][:position] + wrong + lines[bad_line][position + 1:]
    assert lines[bad_line] != GOOD[bad_line]                              # la lectura mala de verdad es distinta de la buena
    r = parse_mrz_td1(*lines)
    assert r["valid"] and r["id"] == "1234567890" and r["last_name"] == "PEREZ GOMEZ"


def test_a_real_error_is_never_accepted_after_the_correction():
    """La corrección solo cambia lo que la POSICIÓN permite (O↔0, I↔1…); un dígito de más o distinto no valida: los dígitos verificadores ICAO siguen mandando."""
    lines = list(GOOD)
    lines[1] = "8" + lines[1][1:]                                    # cambia el primer dígito del nacimiento: 900101 → 800101
    assert parse_mrz_td1(*lines)["valid"] is False
    lines = list(GOOD)
    lines[1] = lines[1][:20] + "9" + lines[1][21:]                    # un dígito del número de cédula cambiado
    assert parse_mrz_td1(*lines)["valid"] is False
    assert parse_mrz_td1("", "", "")["valid"] is False and parse_mrz_td1("basura", "mas basura", "x")["valid"] is False


def test_position_classes_only_touch_the_mismatched_characters():
    assert _fix_by_position("C0L", "aaa") == "COL" and _fix_by_position("COL", "aaa") == "COL"
    assert _fix_by_position("O5I", "ddd") == "051" and _fix_by_position("<<<", "ddd") == "<<<" and _fix_by_position("<<<", "aaa") == "<<<"
    assert _fix_by_position("A1B", "nnn") == "A1B"                    # alfanumérico: no se toca


# ------------------------------------------------------------------ preparación de la imagen
def test_image_variants_are_binary_or_stretched_and_resized():
    rng = np.random.default_rng(1)
    arr = (rng.random((200, 150, 3)) * 255).astype("uint8")
    fijo, otsu, contraste = (mrz_ocr._preprocess(arr, v) for v in range(len(mrz_ocr.VARIANTS)))
    assert fijo.size == (150, 200) and set(np.unique(np.asarray(fijo))) <= {0, 255}                 # la variante 0 es la de siempre: umbral fijo, sin cambiar el tamaño
    assert otsu.width == 1200 and set(np.unique(np.asarray(otsu))) <= {0, 255}
    assert contraste.width == 1200 and len(np.unique(np.asarray(contraste))) > 2
    assert mrz_ocr._preprocess(arr).size == fijo.size                                                # sin variante = la 0
    dark = np.full((50, 50), 30, dtype="uint8")
    assert mrz_ocr._otsu_threshold(dark) in range(0, 256)


# ------------------------------------------------------------------ endpoint: orientación candidata y variantes
@pytest.fixture
def station(client, factory):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso")
    login(client, "root")
    buf = io.BytesIO()
    Image.fromarray(np.full((40, 60, 3), 200, dtype="uint8")).save(buf, format="PNG")
    return client, ev, buf.getvalue()


def _scan(station):
    client, ev, png = station
    return client.post(f"/api/events/{ev.id}/cedula-mrz-scan", files={"file": ("c.png", png, "image/png")})


def _script(monkeypatch, answers):
    calls = []

    def fake(image_array, variant=0):
        calls.append(variant)
        return answers[len(calls) - 1] if len(calls) <= len(answers) else []

    monkeypatch.setattr("app.routers.cedula.extract_mrz_lines", fake)
    return calls


BROKEN = [GOOD[0], GOOD[1][:20] + "9" + GOOD[1][21:], GOOD[2]]            # 3 líneas pero el dígito verificador no cuadra


def test_a_candidate_orientation_tries_the_next_image_preparation_until_one_validates(station, monkeypatch):
    calls = _script(monkeypatch, [[], BROKEN, GOOD])                     # rotación 0: nada → siguiente; rotación 1: variante 0 inválida, variante 1 válida
    r = _scan(station)
    assert r.status_code == 200 and r.json() == {"id": "1234567890", "first_name": "ANA MARIA", "last_name": "PEREZ GOMEZ"}
    assert calls == [0, 0, 1]                                            # una sola llamada en la orientación sin texto; variantes solo donde hubo 3 líneas


def test_an_orientation_without_three_lines_does_not_spend_the_other_variants(station, monkeypatch):
    calls = _script(monkeypatch, [])
    r = _scan(station)
    assert r.status_code == 422 and "No se detectó la zona MRZ" in r.json()["detail"]
    assert calls == [0, 0, 0, 0]                                         # 4 orientaciones × la variante 0 (ninguna dio 3 líneas)


def test_lines_that_never_validate_ask_for_a_new_photo(station, monkeypatch):
    calls = _script(monkeypatch, [[], BROKEN, BROKEN, BROKEN])
    r = _scan(station)
    assert r.status_code == 422 and "dígito verificador" in r.json()["detail"]
    assert calls[:4] == [0, 0, 1, 2]


def test_the_first_valid_reading_stops_the_search(station, monkeypatch):
    calls = _script(monkeypatch, [GOOD])
    assert _scan(station).status_code == 200 and calls == [0]
