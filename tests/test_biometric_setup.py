"""Paso guiado de biometría del evento: las reglas se validan EN EL SERVIDOR (lo que protege) y el resumen dice en lenguaje simple qué pasará en la puerta."""
import pytest

from tests.conftest import login


@pytest.fixture(autouse=True)
def company_env(monkeypatch):
    for k, v in {"COMPANY_NAME": "Golden Eventos y Logística S.A.S.", "COMPANY_NIT": "901542833-2", "PRIVACY_EMAIL": "soporteit@goldenlogisticas.com", "DOMAIN": "golden-eventos.com"}.items():
        monkeypatch.setenv(k, v)


def _put(client, ev, **body):
    return client.put(f"/api/events/{ev.id}/biometric-setup", json=body)


def _as(client, factory, role, name):
    factory.staff(role, name)
    login(client, name)


def test_a_third_party_event_cannot_use_faces_without_the_organizers_data(client, factory, db):
    _as(client, factory, "coordinador", "coord1")
    ev = factory.event("en_proceso")
    r = _put(client, ev, facial_enabled=True, controller_mode="tercero")
    assert r.status_code == 400 and "razón social" in r.json()["detail"] and "NIT" in r.json()["detail"] and "correo de privacidad" in r.json()["detail"]
    db.refresh(ev)
    assert ev.facial_enabled is False and ev.controller_mode == "golden"                   # todo o nada: no quedó a medias
    ok = _put(client, ev, facial_enabled=True, controller_mode="tercero", organizer_name="Org S.A.", organizer_nit="800.1", organizer_privacy_email="dpo@org.test")
    assert ok.status_code == 200 and ok.json()["config"]["facial_enabled"] is True and ok.json()["ready"] is True
    # el interruptor manual de siempre también respeta la regla
    other = factory.event("en_proceso", controller_mode="tercero")
    assert client.put(f"/api/events/{other.id}/facial-enabled", json={"enabled": True}).status_code == 400
    assert client.put(f"/api/events/{ev.id}/facial-enabled", json={"enabled": True}).status_code == 200


def test_defaults_are_the_safe_ones_and_options_need_faces_on(client, factory, db):
    _as(client, factory, "coordinador", "coord1")
    ev = factory.event("en_proceso")
    assert (ev.aceptar_enabled, ev.consent_prompt_mode, ev.precalculo_autorizado, ev.client_photos_before, ev.facial_enabled) == (False, "once", False, False, False)
    assert _put(client, ev, aceptar_enabled=True).status_code == 400                         # /aceptar sin rostro no tiene sentido
    assert _put(client, ev, facial_enabled=True, aceptar_enabled=True, consent_prompt_mode="every_scan").status_code == 200
    assert _put(client, ev, consent_prompt_mode="siempre").status_code == 400


def test_precalculation_needs_third_party_photos_annex_and_guarantee_and_only_a_super_admin(client, factory, db):
    _as(client, factory, "super_admin", "sup")
    own = factory.event("en_proceso", facial_enabled=True, client_photos_before=True)
    url = lambda e: f"/api/events/{e.id}/precalculo-autorizado"          # noqa: E731
    full = {"enabled": True, "anexo_ref": "ANX-7", "anexo_fecha": "2026-10-01", "garantia": True}
    assert client.put(url(own), json=full).status_code == 400                                 # evento propio con fotos previas: NO se pre-calcula (el vector se calcula al aceptar)
    third = factory.event("en_proceso", facial_enabled=True, controller_mode="tercero", organizer_name="O", organizer_nit="1", organizer_privacy_email="o@o.test")
    r = client.put(url(third), json=full)
    assert r.status_code == 400 and "fotos antes del evento" in r.json()["detail"]            # el cliente no entregará fotos previas
    assert _put(client, third, client_photos_before=True).status_code == 200
    assert client.put(url(third), json={**full, "garantia": False}).status_code == 400 and client.put(url(third), json={**full, "anexo_ref": ""}).status_code == 400
    assert client.put(url(third), json=full).json()["precalculo_autorizado"] is True
    db.refresh(third)
    assert third.precalculo_garantia is True
    # 23-nov-2026 (Juan David): con rostro y fotos del cliente el modo de un clic queda encendido (lo condiciona el anexo firmado, biometric_setup.apply_precalc_default);
    # pasar a evento propio ya no lo apaga, quitar las fotos previas sí
    assert _put(client, third, controller_mode="golden").json()["config"]["precalculo_autorizado"] is True
    r = _put(client, third, client_photos_before=False)
    assert r.json()["config"]["precalculo_autorizado"] is False


def test_summary_explains_the_door_in_plain_language_and_lists_what_is_missing(client, factory, db):
    _as(client, factory, "coordinador", "coord1")
    ev = factory.event("en_proceso")
    off = client.get(f"/api/events/{ev.id}/biometric-setup").json()
    assert off["ready"] is True and off["missing"] == [] and off["headline"] == "✅ Listo: este evento no usa biometría" and "cédula o QR" in " ".join(off["door"])      # sin rostro no es un problema
    on = _put(client, ev, facial_enabled=True, aceptar_enabled=True, client_photos_before=True).json()
    text = " ".join(on["door"])
    assert on["ready"] is True and "Golden es el Responsable único" in text and "una sola vez" in text and "celular" in text and "NO se calcula hasta que la persona acepte" in text and "nunca se bloquea" in text
    third = factory.event("en_proceso", controller_mode="tercero", organizer_name="Org", organizer_nit="1", organizer_privacy_email="o@o.test", facial_enabled=True, client_photos_before=True)
    s = client.get(f"/api/events/{third.id}/biometric-setup").json()
    assert s["ready"] is False and any("super administrador" in m for m in s["missing"])


def test_company_markers_unresolved_in_production_show_up_as_missing(client, factory, monkeypatch):
    _as(client, factory, "coordinador", "coord1")
    ev = factory.event("en_proceso", facial_enabled=True)
    monkeypatch.delenv("COMPANY_NIT")
    s = client.get(f"/api/events/{ev.id}/biometric-setup").json()
    assert s["ready"] is True                                                                  # fuera de producción el marcador solo se ve en el texto
    monkeypatch.setenv("ENVIRONMENT", "production")
    s = client.get(f"/api/events/{ev.id}/biometric-setup").json()
    assert s["ready"] is False and any("COMPANY_NIT" in m for m in s["missing"])


def test_bulk_photos_are_refused_unless_parameters_say_face_with_client_photos(client, factory, db, monkeypatch):
    import io
    import zipfile

    from PIL import Image
    _as(client, factory, "coordinador", "coord1")
    ev = factory.event("en_proceso", controller_mode="tercero")
    buf, img = io.BytesIO(), io.BytesIO()
    Image.new("RGB", (40, 40), (1, 2, 3)).save(img, "JPEG")
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("1001.jpg", img.getvalue())
    csv = "\n".join(["id,nombres,apellidos,fecha de nacimiento", "1001,Ana,Mora,1990-01-01", ""]).encode()
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id), "photos_authorized": "true"}, files={"roster_file": ("b.csv", csv, "text/csv"), "zip_file": ("f.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 400 and "origen A" in r.json()["detail"] and "Parámetros" in r.json()["detail"]      # Fase 0: la carga ya no enciende el rostro
    db.refresh(ev)
    assert ev.facial_enabled is False


def test_parameters_page_shows_the_guided_step(client, factory):
    _as(client, factory, "coordinador", "coord1")
    ev = factory.event("en_proceso")
    page = client.get(f"/kiosk/{ev.id}/parametros")
    assert page.status_code == 200 and "Reconocimiento facial: paso guiado" in page.text and "bsSummary" in page.text and "bsPhotos" in page.text and "biometric-setup" in page.text
