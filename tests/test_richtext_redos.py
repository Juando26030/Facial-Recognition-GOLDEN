"""R3-01 (Fase 3): `richtext._FORMAT_RE` era exponencial con atributos de valor vacío («<b a= a= a= !»). No usa base de datos."""
import time

from app import richtext


def test_format_re_is_linear_on_empty_unquoted_values():
    t = time.perf_counter()
    for payload in ("<b" + " a=" * 3000 + " !", "<b" + ' a="x"' * 3000 + " !", "<b" + " a=1" * 3000 + " !", "<b" + " a='" * 2000, "<b" + " a" * 5000):
        richtext.has_format(payload)
    assert time.perf_counter() - t < 0.5


def test_short_attack_string_is_instant():
    t = time.perf_counter()
    assert not richtext.has_format("<b" + " a=" * 120 + " !")       # ~360 caracteres: antes tardaba horas
    assert time.perf_counter() - t < 0.2


def test_real_tags_still_detected():
    for ok in ("<b>x</b>", '<span style="color:red">x</span>', "<p class=x style='a'>", "<br/>", "</div>"):
        assert richtext.has_format(ok), ok
    for no in ("a < b", "<b && c>", "texto plano"):
        assert not richtext.has_format(no), no


def test_huge_text_is_not_evaluated_by_the_regex():
    t = time.perf_counter()
    assert richtext.has_format("x" * 50000)           # pasa al saneador, que lo recorta o rechaza
    assert time.perf_counter() - t < 0.1
