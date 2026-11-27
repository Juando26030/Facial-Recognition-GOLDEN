"""«Configurar el evento por cuestionario» (app/setup_quiz.py): reglas puras, sin base de datos (corre con --noconftest)."""
import re
from pathlib import Path

from app import setup_quiz as sq

TPL = (Path(__file__).resolve().parent.parent / "templates" / "kiosk_parametros.html").read_text(encoding="utf-8")
IDS = set(re.findall(r'\bid="([^"{}]+)"', TPL)) | {m for m in re.findall(r'id="\{\{ col \}\}"', TPL)}
SEARCH_COLS = {"code_search_registro", "code_search_inventario", "code_search_zonas"}          # se generan con un for en la plantilla
RADIOS = {(re.search(r'name="([^"]+)"', t).group(1), re.search(r'value="([^"]+)"', t).group(1))
          for t in re.findall(r'<input[^>]*type="radio"[^>]*>', TPL) if 'name="' in t and 'value="' in t}


def state(**kw):
    base = {"roster_loaded": False, "forms": 0, "has_logo": False, "brand_color": False, "unlock_pw": False, "annex": False, "organizer": False,
            "badge_designed": False, "print_routes": 0, "categories": [], "per_category": False, "category_templates": [], "cert_designed": False,
            "areas": 0, "items": 0, "assign_holder": False, "assign_dep": False, "dependents": 0, "optional_fields": False, "person_form": False}
    base.update(kw)
    return base


def test_preguntas_bien_formadas():
    ids = [q["id"] for q in sq.QUESTIONS]
    assert len(ids) == len(set(ids))
    secs = {s for s, _ in sq.SECTIONS}
    for q in sq.QUESTIONS:
        assert q["section"] in secs and q["text"].endswith("?")
        vals = [o["v"] for o in q["options"]]
        assert len(vals) >= 2 and len(vals) == len(set(vals)), q["id"]
        for dep, allowed in q["when"].items():
            assert dep in sq.BY_ID, (q["id"], dep)
            assert set(allowed) <= {o["v"] for o in sq.BY_ID[dep]["options"]}, (q["id"], dep)
        for o in q["options"]:
            for op in o["set"]:
                if op["k"] == "state":
                    assert op["key"] in sq.state_flags(state())
                    continue
                assert op["label"], (q["id"], op)


def test_cada_control_existe_en_la_pantalla():
    """Cada interruptor u opción que mueve el cuestionario está en Parámetros con ese id o ese valor (si no, la respuesta no haría nada)."""
    for q in sq.QUESTIONS:
        for o in q["options"]:
            for op in o["set"]:
                if op["k"] == "radio":
                    assert (op["name"], op["v"]) in RADIOS, (q["id"], op)
                elif op["k"] != "state":
                    assert op["id"] in IDS or op["id"] in SEARCH_COLS, (q["id"], op)


def test_cada_accion_se_marca_en_un_bloque_que_existe():
    for a in sq.ACTIONS:
        assert a["target"] in IDS, a["id"]
        assert a["title"] and a["text"]


def test_la_pestana_del_cuestionario_va_primero():
    tabs = re.findall(r'role="tab" id="(tab_[a-z]+)"', TPL)
    assert tabs[0] == "tab_cuestionario" and tabs[1] == "tab_registro"
    assert TPL.count("data-group-action") == len(tabs)          # cada pestaña puede decir «Requiere acción»


def test_limpia_respuestas():
    out = sq.clean_answers({"zonas": "si", "zonas2": "si", "repartir": "tal vez", "quien": 3, "lista": "base"})
    assert out == {"zonas": "si", "lista": "base"}
    assert sq.clean_answers(None) == {}


def test_servidor_local_sin_preguntas_de_rostro():
    ids = {q["id"] for q in sq.questions_for(local_server=True)}
    assert "rostro" not in ids and "celular" not in ids and "zonas" in ids
    assert "formpersona" not in ids and "formpersona" in {q["id"] for q in sq.questions_for(person_form=True)}
    assert sq.clean_answers({"rostro": "si"}, sq.questions_for(local_server=True)) == {}


def test_preguntas_que_dependen_de_otras():
    assert not sq.visible("fotos", {"rostro": "no"})
    assert sq.visible("fotos", {"rostro": "si"})
    assert not sq.visible("minimo", {"zonas": "no", "permanencia": "si"})          # la cadena entera: sin zonas no hay permanencia
    assert sq.visible("minimo", {"zonas": "si", "permanencia": "si"})
    assert sq.visible("buscazonas", {"codigo": "si", "zonas": "si"}) and not sq.visible("buscazonas", {"codigo": "si"})


def test_acciones_segun_respuestas_y_estado():
    ans = {"repartir": "si", "quien": "elige", "zonas": "si", "zonasbloq": "si", "invbloq": "si"}
    acts = {a["id"]: a for a in sq.actions(ans, state(), 7)}
    assert set(acts) == {"items", "areas", "lock_pw"}          # la contraseña, una sola vez aunque la pidan zonas e inventario
    assert not acts["items"]["done"] and acts["items"]["target"] == "qzInventoryItem"
    acts = {a["id"]: a for a in sq.actions(ans, state(items=3, areas=1, unlock_pw=True), 7)}
    assert all(a["done"] for a in acts.values())


def test_respuestas_ocultas_no_piden_nada():
    acts = sq.actions({"repartir": "no", "quien": "elige"}, state(), 1)
    assert acts == []


def test_engranaje_cerrado_no_exige_contrasena():
    """Es lo de fábrica: el coordinador lo abre igual; la contraseña solo se pide al bloquear zonas o inventario."""
    assert sq.actions({"gear": "no"}, state(), 1) == []


def test_escarapela_por_rol():
    ans = {"roles": "si", "imprime": "si", "escarapelarol": "si"}
    acts = {a["id"]: a for a in sq.actions(ans, state(badge_designed=True, categories=["VIP", "Prensa"], per_category=True, category_templates=["VIP"]), 5)}
    assert acts["categories"]["done"] and acts["badge"]["done"]
    assert not acts["badge_per_cat"]["done"] and acts["badge_per_cat"]["link"] == "/kiosk/5/escarapela"
    acts = {a["id"]: a for a in sq.actions(ans, state(badge_designed=True, categories=["VIP", "Prensa"], per_category=True, category_templates=["Prensa", "VIP"]), 5)}
    assert acts["badge_per_cat"]["done"]


def test_rostro_con_fotos_del_cliente():
    acts = {a["id"]: a for a in sq.actions({"rostro": "si", "fotos": "cliente"}, state(), 2)}
    assert set(acts) == {"annex", "organizer"}
    acts = {a["id"] for a in sq.actions({"rostro": "si", "fotos": "golden"}, state(), 2)}
    assert acts == set()


def test_inventario_por_base_y_dependientes():
    ans = {"repartir": "si", "quien": "base", "dependientes": "si"}
    acts = {a["id"]: a for a in sq.actions(ans, state(assign_holder=True), 2)}
    assert acts["assign"]["done"] and not acts["dependents"]["done"]
    acts = {a["id"]: a for a in sq.actions(ans, state(assign_holder=True, assign_dep=True, dependents=4), 2)}
    assert acts["dependents"]["done"]
