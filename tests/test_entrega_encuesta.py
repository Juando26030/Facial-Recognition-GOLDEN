"""Fase 5 (B): entrega al cliente de un evento Facturado: enlace público /entrega/<token> → encuesta de satisfacción → descarga de la base final.

El estado «Facturado» y la base final los construye otra rama: aquí se SIMULAN con monkeypatch sobre `delivery.is_billed` y `delivery.final_db` (la lectura defensiva de app/delivery.py)."""
import pathlib
import re

import pytest

from app import appmode, delivery, jobs, survey_def
from app.models import AuditAction, EventDeliveryLink, Job, SurveyAnswer, SurveyResponse, Tenant
from app.routers import delivery as delivery_router
from app.storage import get_storage
from app.ttlcache import SlidingLimiter
from tests.conftest import login

LINK = re.compile(r"/entrega/([A-Za-z0-9_\-]+)$")
FILE_BYTES = b"cedula,nombre\n1001,Ana\n"


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch):
    monkeypatch.setattr(delivery_router, "_limiter", SlidingLimiter())


@pytest.fixture()
def mails(monkeypatch):
    sent = []
    monkeypatch.setattr("app.delivery.send_mail", lambda to, subject, body, attachments=None, html=None, reply_to=None: sent.append({"to": to, "subject": subject, "body": body, "html": html}) or {"sent": True, "detail": "prueba"})
    return sent


@pytest.fixture()
def env(client, factory, db, monkeypatch):
    """Evento finalizado y «Facturado» (simulado), con base final subida y una comercial dueña del evento."""
    com = factory.staff("comercial", "com1", email="com1@golden.test")
    ev = factory.event("finalizado", commercial=com)
    tenant = db.get(Tenant, ev.tenant_id)
    tenant.contact_email, tenant.contact_name = "cliente@acme.test", "Marta Cliente"
    db.commit()
    get_storage().put("acme/final_db/base_final.xlsx", FILE_BYTES)
    state = {"billed": {ev.id}, "db": {ev.id: ("acme/final_db/base_final.xlsx", "Base final ACME.xlsx")}}
    monkeypatch.setattr(delivery, "is_billed", lambda e: e.id in state["billed"])
    monkeypatch.setattr(delivery, "final_db", lambda e: state["db"].get(e.id))
    state["event"] = ev
    return state


def _staff_link(client, ev, **body):
    login(client, "com1")
    r = client.post(f"/api/events/{ev.id}/delivery/link", json=body)
    assert r.status_code == 200, r.text
    url = r.json()["link"]
    client.post("/logout")
    client.cookies.clear()
    return LINK.search(url).group(1)


def _answers(**over):
    base = {"q1_experience": {"choice": "excellent", "comment": "Todo muy bien"}, "q2_staff": {"choice": "good"}, "q3_coordinator": {"choice": "excellent"},
            "q4_commercial": {"choice": "bad", "comment": "Tardó en responder"}, "q5_speed": {"choice": "Buenos"}, "q6_badges": {"choice": "na"},
            "q7_nps": {"choice": "9", "comment": "Los recomendaría"}, "q8_next_event": {"choice": "Sí", "comment": "En marzo"}}
    base.update(over)
    return {"answers": base}


# ------------------------------------------------------------------------------------------------ enlace válido, revocado, inexistente
def test_valid_link_shows_greeting_event_and_survey_without_login(client, env):
    token = _staff_link(client, env["event"])
    r = client.get(f"/entrega/{token}")
    assert r.status_code == 200
    ev = env["event"]
    assert ev.name in r.text and "ACME" in r.text and "primero diligencie esta encuesta" in r.text
    assert "readonly" in r.text and "Excelente" in r.text and "No aplica" in r.text and "Descargar base de datos" in r.text
    assert r.headers["cache-control"] == "no-store" and "noindex" in r.headers["x-robots-tag"]
    assert 'id="doneCard"' in r.text and "hidden" in r.text.split('id="doneCard"')[1][:80]           # la descarga está oculta hasta enviar la encuesta


def test_unknown_malformed_and_revoked_links_all_look_the_same(client, env, db):
    token = _staff_link(client, env["event"])
    ok = client.get(f"/entrega/{token}")
    assert ok.status_code == 200
    db.query(EventDeliveryLink).update({"revoked_at": delivery.utcnow()})
    db.commit()
    for t in (token, "x" * 43, "corto", "a" * 200):
        r = client.get(f"/entrega/{t}")
        assert r.status_code == 404 and "Enlace no disponible" in r.text and env["event"].name not in r.text
        assert client.post(f"/entrega/{t}/encuesta", json=_answers()).status_code == 404
        assert client.get(f"/entrega/{t}/base").status_code == 404


def test_token_is_not_stored_and_regenerating_kills_the_old_link(client, env, db):
    old = _staff_link(client, env["event"])
    row = db.query(EventDeliveryLink).one()
    assert row.token_hash == delivery.hash_token(old) and old not in (row.token_hash, row.nonce)
    new = _staff_link(client, env["event"], regenerate=True)
    assert new != old
    assert client.get(f"/entrega/{old}").status_code == 404 and client.get(f"/entrega/{new}").status_code == 200
    assert db.query(EventDeliveryLink).filter(EventDeliveryLink.revoked_at.is_(None)).count() == 1
    again = _staff_link(client, env["event"])                                   # sin regenerar devuelve el mismo enlace
    assert again == new and db.query(EventDeliveryLink).count() == 2


def test_the_page_is_served_by_the_public_service_only():
    assert appmode.route_allowed("/entrega/{token}", mode="publico") and appmode.route_allowed("/entrega/{token}/base", mode="publico")
    assert not appmode.route_allowed("/entrega/{token}", mode="web") and not appmode.route_allowed("/entrega/{token}", mode="biometria")
    assert appmode.route_allowed("/api/events/{event_id}/delivery", mode="web") and not appmode.route_allowed("/api/events/{event_id}/delivery", mode="publico")


# ------------------------------------------------------------------------------------------------ la descarga exige encuesta, Facturado y base final
def test_no_download_without_the_survey_then_download_after_it(client, env, db):
    token = _staff_link(client, env["event"])
    r = client.get(f"/entrega/{token}/base")
    assert r.status_code == 403 and "primero diligencie la encuesta" in r.json()["detail"]
    s = client.post(f"/entrega/{token}/encuesta", json=_answers())
    assert s.status_code == 200 and s.json()["can_download"] is True
    d = client.get(f"/entrega/{token}/base")
    assert d.status_code == 200 and d.content == FILE_BYTES
    assert d.headers["content-disposition"].startswith("attachment") and "Base final ACME.xlsx" in d.headers["content-disposition"]
    assert "no-store" in d.headers["cache-control"]
    rows = db.query(AuditAction).filter(AuditAction.action == "delivery_download").all()
    assert len(rows) == 1 and rows[0].entity == "delivery_link" and "@" not in (rows[0].detail or "") and "1001" not in str(rows[0].detail)       # solo conteo


def test_no_download_when_the_event_is_no_longer_billed(client, env):
    token = _staff_link(client, env["event"])
    assert client.post(f"/entrega/{token}/encuesta", json=_answers()).status_code == 200
    env["billed"].clear()                                                       # se deshizo el «Facturado»
    r = client.get(f"/entrega/{token}/base")
    assert r.status_code == 404 and "todavía no está habilitada" in r.json()["detail"]
    assert "todavía no está habilitada" in client.get(f"/entrega/{token}").text
    assert client.post(f"/entrega/{token}/encuesta", json=_answers()).status_code == 404


def test_no_download_when_there_is_no_final_base_but_the_survey_still_goes(client, env):
    token = _staff_link(client, env["event"])
    env["db"].clear()
    s = client.post(f"/entrega/{token}/encuesta", json=_answers())
    assert s.status_code == 200 and s.json()["can_download"] is False
    r = client.get(f"/entrega/{token}/base")
    assert r.status_code == 404 and "base de datos final" in r.json()["detail"]


def test_download_limit_per_link_and_hour(client, env, monkeypatch):
    monkeypatch.setattr(delivery, "DOWNLOADS_PER_HOUR", 2)
    token = _staff_link(client, env["event"])
    client.post(f"/entrega/{token}/encuesta", json=_answers())
    assert [client.get(f"/entrega/{token}/base").status_code for _ in range(3)] == [200, 200, 429]


def test_real_is_billed_requires_the_billed_state_and_closes_with_the_archive(factory, db):
    from app import event_rules
    from app.timeutil import utcnow
    ev = factory.event("finalizado")
    assert delivery.is_billed(ev) is False                                      # sin «Facturado» nada se entrega
    assert delivery.final_db(ev) is None                                        # sin la base final subida tampoco
    if "client_delivery" not in event_rules.RULES:                              # antes de integrar la rama del estado Facturado: base finalizado + billed_at
        ev.billed_at = utcnow()
        assert delivery.is_billed(ev) is True
        ev.status = "en_proceso"
        assert delivery.is_billed(ev) is False
        ev.status = "finalizado"
        ev.data_archived_at = utcnow()
        assert delivery.is_billed(ev) is False                                  # base archivada (L7): el enlace se cierra
        ev.data_archived_at, ev.archived_at = None, utcnow()
        assert delivery.is_billed(ev) is False                                  # evento archivado: también
    ev.final_db_key, ev.final_db_name = "acme/final_db/x.xlsx", "x.xlsx"
    assert delivery.final_db(ev) == ("acme/final_db/x.xlsx", "x.xlsx")


# ------------------------------------------------------------------------------------------------ la encuesta guarda filas normalizadas
def test_survey_is_stored_apart_with_normalized_scores(client, env, db):
    token = _staff_link(client, env["event"])
    r = client.post(f"/entrega/{token}/encuesta", json=_answers())
    assert r.status_code == 200
    resp = db.query(SurveyResponse).one()
    ev = env["event"]
    assert (resp.event_id, resp.tenant_id, resp.survey_version, resp.nps_score) == (ev.id, "acme", survey_def.SURVEY_VERSION, 9)
    assert resp.avg_score == 2.2                                                # q1=3, q2=2, q3=3, q4=1, q5=2 (11/5); q6 «No aplica» no cuenta
    assert resp.comment_count == 4 and resp.submitted_at is not None and resp.delivery_link_id == db.query(EventDeliveryLink).one().id
    assert resp.ip_hash is None or len(resp.ip_hash) == 16
    by_q = {a.question_id: a for a in db.query(SurveyAnswer).filter_by(response_id=resp.id)}
    assert set(by_q) == set(survey_def.BY_ID)
    assert (by_q["q1_experience"].score, by_q["q1_experience"].choice_text, by_q["q1_experience"].comment) == (3, "Excelente", "Todo muy bien")
    assert (by_q["q2_staff"].score, by_q["q2_staff"].choice_text) == (2, "Buena")
    assert (by_q["q4_commercial"].score, by_q["q4_commercial"].choice_text) == (1, "Mala")
    assert (by_q["q5_speed"].score, by_q["q5_speed"].choice_text) == (2, "Buenos")                  # la forma gramatical de la pregunta 5
    assert (by_q["q6_badges"].score, by_q["q6_badges"].choice_text) == (None, "No aplica")
    assert (by_q["q7_nps"].score, by_q["q7_nps"].comment) == (9, "Los recomendaría")
    assert (by_q["q8_next_event"].score, by_q["q8_next_event"].choice_text, by_q["q8_next_event"].comment) == (None, "Sí", "En marzo")
    assert all(a.event_id == ev.id and a.tenant_id == "acme" and a.submitted_at == resp.submitted_at and a.survey_version == 1 for a in by_q.values())


def test_question_8_is_optional_and_comments_are_optional(client, env, db):
    token = _staff_link(client, env["event"])
    body = _answers()
    body["answers"].pop("q8_next_event")
    for q in ("q1_experience", "q7_nps"):
        body["answers"][q].pop("comment", None)
    assert client.post(f"/entrega/{token}/encuesta", json=body).status_code == 200
    assert db.query(SurveyAnswer).filter_by(question_id="q8_next_event").count() == 0


@pytest.mark.parametrize("mutate,needle", [
    (lambda a: a.pop("q1_experience"), "pregunta 1"),
    (lambda a: a.update(q2_staff={"choice": "regular"}), "pregunta 2"),
    (lambda a: a.update(q7_nps={"choice": "11"}), "pregunta 7"),
    (lambda a: a.update(q7_nps={"choice": "abc"}), "pregunta 7"),
    (lambda a: a.update(q5_speed={"choice": "na"}), "pregunta 5"),                  # «No aplica» solo existe en la 6
    (lambda a: a.update(q8_next_event={"choice": "Tal vez"}), "pregunta 8"),
])
def test_invalid_surveys_are_rejected_in_spanish_and_nothing_is_saved(client, env, db, mutate, needle):
    token = _staff_link(client, env["event"])
    body = _answers()
    mutate(body["answers"])
    r = client.post(f"/entrega/{token}/encuesta", json=body)
    assert r.status_code == 400 and needle in r.json()["detail"]
    assert db.query(SurveyResponse).count() == 0 and db.query(SurveyAnswer).count() == 0
    assert client.get(f"/entrega/{token}/base").status_code == 403


def test_question_6_may_be_left_out_and_the_summary_averages_only_quality_questions():
    body = _answers()
    body["answers"].pop("q6_badges")
    rows = survey_def.validate(body)                                            # la 6 es opcional (solo aplica si Golden suministró escarapelas)
    assert "q6_badges" not in {r["question_id"] for r in rows}
    s = survey_def.summarize(survey_def.validate(_answers()))
    assert s == {"nps_score": 9, "avg_score": 2.2, "comment_count": 4}


def test_long_comments_are_cut_and_whitespace_is_collapsed():
    rows = survey_def.validate(_answers(q1_experience={"choice": "good", "comment": "  hola \n\n  mundo " + "x" * 5000}))
    c = next(r for r in rows if r["question_id"] == "q1_experience")["comment"]
    assert c.startswith("hola mundo") and len(c) == survey_def.COMMENT_MAX


# ------------------------------------------------------------------------------------------------ una sola respuesta por evento
def test_only_one_survey_per_event_even_after_regenerating_the_link(client, env, db):
    token = _staff_link(client, env["event"])
    assert client.post(f"/entrega/{token}/encuesta", json=_answers()).status_code == 200
    again = client.post(f"/entrega/{token}/encuesta", json=_answers(q7_nps={"choice": "0"}))
    assert again.status_code == 409 and "Ya recibimos" in again.json()["detail"] and again.json()["can_download"] is True
    assert db.query(SurveyResponse).count() == 1 and db.query(SurveyResponse).one().nps_score == 9           # no se reemplaza
    new = _staff_link(client, env["event"], regenerate=True)
    assert client.post(f"/entrega/{new}/encuesta", json=_answers()).status_code == 409
    assert client.get(f"/entrega/{new}/base").status_code == 200                # la encuesta ya estaba enviada: no se repite
    page = client.get(f"/entrega/{new}").text
    assert "hidden" in page.split('id="surveyForm"')[1][:200] and "hidden" not in page.split('id="doneCard"')[1][:30]          # ya contestada: se muestra la descarga, no la encuesta


def test_survey_table_has_the_unique_index_per_event(db, factory):
    from sqlalchemy.exc import IntegrityError
    ev = factory.event("finalizado")
    db.add(SurveyResponse(event_id=ev.id, tenant_id="acme", survey_version=1))
    db.commit()
    db.add(SurveyResponse(event_id=ev.id, tenant_id="acme", survey_version=1))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ------------------------------------------------------------------------------------------------ permisos del lado interno
@pytest.mark.parametrize("who,expected", [("com1", 200), ("admin1", 200), ("root1", 200), ("coord1", 403), ("dig1", 403)])
def test_only_commercial_admin_and_super_admin_use_the_delivery_block(client, factory, env, mails, who, expected):
    factory.staff("admin", "admin1")
    factory.staff("super_admin", "root1")
    factory.staff("coordinador", "coord1")
    factory.staff("digitador", "dig1")
    ev = env["event"]
    login(client, who)
    assert client.get(f"/api/events/{ev.id}/delivery").status_code == expected
    assert client.post(f"/api/events/{ev.id}/delivery/link", json={}).status_code == expected
    assert client.post(f"/api/events/{ev.id}/delivery/send-email", json={"confirm": True}).status_code in (expected, 409)


def test_anonymous_cannot_reach_the_staff_routes(client, env):
    ev = env["event"]
    assert client.get(f"/api/events/{ev.id}/delivery").status_code == 401
    assert client.post(f"/api/events/{ev.id}/delivery/link", json={}).status_code == 401
    assert client.post(f"/api/events/{ev.id}/delivery/send-email", json={"confirm": True}).status_code == 401


def test_the_block_only_exists_when_the_event_is_billed(client, env):
    ev = env["event"]
    login(client, "com1")
    on = client.get(f"/api/events/{ev.id}/delivery").json()
    assert on["eligible"] is True and on["has_final_db"] is True and on["final_db_name"] == "Base final ACME.xlsx" and on["survey_done"] is False
    assert on["recipient"] == "cliente@acme.test" and on["recipient_source"] == "tenant"
    env["billed"].clear()
    off = client.get(f"/api/events/{ev.id}/delivery").json()
    assert off["eligible"] is False and off["link"] is None
    assert client.post(f"/api/events/{ev.id}/delivery/link", json={}).status_code == 409
    assert client.post(f"/api/events/{ev.id}/delivery/send-email", json={"confirm": True}).status_code == 409


def test_modal_has_the_delivery_block_for_commercial_roles_only():
    html = pathlib.Path("templates/_event_edit_modal.html").read_text(encoding="utf-8")
    block = html.split('id="eeDeliveryGroup"')[1].split("</details>")[0]
    assert 'id="eeDeliveryMailChk"' in block and 'id="eeDeliveryMailChk" checked' not in block        # la casilla viene DESMARCADA
    assert 'id="eeDeliverySend" disabled' in block and "Regenerar enlace" in block and "Copiar" in block
    assert 'staff_role in ("comercial", "admin", "super_admin")' in html.split('id="eeDeliveryGroup"')[0][-400:]
    assert "window.copyText" in html and "confirm: true" in html


# ------------------------------------------------------------------------------------------------ correo
def test_mail_is_queued_only_when_the_box_is_checked(client, env, mails, db):
    ev = env["event"]
    login(client, "com1")
    client.post(f"/api/events/{ev.id}/delivery/link", json={})
    for body in ({}, {"confirm": False}, {"confirm": "true"}, {"send": True}):
        r = client.post(f"/api/events/{ev.id}/delivery/send-email", json=body)
        assert r.status_code == 400 and "Marque" in r.json()["detail"]
    assert mails == [] and db.query(Job).filter_by(kind="delivery_mail").count() == 0
    r = client.post(f"/api/events/{ev.id}/delivery/send-email", json={"confirm": True})
    assert r.status_code == 200 and r.json()["queued"] is True
    assert len(mails) == 1                                                      # la cola corre en el acto en las pruebas
    mail = mails[0]
    token = delivery.token_of(db.query(EventDeliveryLink).one())
    assert mail["to"] == "cliente@acme.test" and f"/entrega/{token}" in mail["body"] and f"/entrega/{token}" in mail["html"]
    assert ev.name in mail["subject"] and "encuesta" in mail["body"] and "base de datos" in mail["body"]
    assert "contraseña" in mail["body"] and "Marta Cliente" in mail["body"]
    job = db.query(Job).filter_by(kind="delivery_mail").one()
    assert "cliente@acme.test" not in job.payload_json and token not in job.payload_json              # la cola no lleva correos ni el token
    assert db.query(AuditAction).filter_by(action="delivery_mail").count() == 1


def test_mail_is_not_repeated_within_the_hour(client, env, mails):
    ev = env["event"]
    login(client, "com1")
    assert client.post(f"/api/events/{ev.id}/delivery/send-email", json={"confirm": True}).status_code == 200
    again = client.post(f"/api/events/{ev.id}/delivery/send-email", json={"confirm": True})
    assert again.status_code == 429 and len(mails) == 1


def test_mail_needs_a_contact_email_and_a_final_base(client, env, mails, db):
    ev = env["event"]
    login(client, "com1")
    db.get(Tenant, ev.tenant_id).contact_email = "no-es-un-correo"
    db.commit()
    r = client.post(f"/api/events/{ev.id}/delivery/send-email", json={"confirm": True})
    assert r.status_code == 409 and "correo de contacto" in r.json()["detail"]
    assert client.get(f"/api/events/{ev.id}/delivery").json()["recipient"] is None
    db.get(Tenant, ev.tenant_id).contact_email = "cliente@acme.test"
    db.commit()
    env["db"].clear()
    r = client.post(f"/api/events/{ev.id}/delivery/send-email", json={"confirm": True})
    assert r.status_code == 409 and "base de datos final" in r.json()["detail"]
    assert mails == []


def test_contact_falls_back_to_a_client_account_of_the_event(client, factory, env, db):
    ev = env["event"]
    db.get(Tenant, ev.tenant_id).contact_email = None
    db.commit()
    assert delivery.client_contact(db, ev) is None
    cli = factory.staff("cliente", "cli1", email="Cuenta@Acme.Test", full_name="Cuenta Acme")
    factory.authorize(ev, cli)
    assert delivery.client_contact(db, ev) == {"email": "cuenta@acme.test", "name": "Cuenta Acme", "source": "client_account"}


def test_a_queued_mail_dies_with_a_revoked_link(client, env, mails, db):
    ev = env["event"]
    login(client, "com1")
    client.post(f"/api/events/{ev.id}/delivery/link", json={})
    link = db.query(EventDeliveryLink).one()
    link.revoked_at = delivery.utcnow()
    db.commit()
    delivery.run_mail({"event_id": ev.id, "link_id": link.id, "base": "http://test.local"})
    assert mails == []                                                          # no se manda un enlace muerto


def test_mail_text_has_no_passwords_or_personal_data_of_attendees():
    m = delivery.render_mail(event_name="Congreso <b>X</b>", contact_name="", url="http://test.local/entrega/abc")
    assert m["text"].startswith("Hola:") and "&lt;b&gt;" in m["html"] and "<b>X</b>" not in m["html"]
    assert "http://test.local/entrega/abc" in m["text"]


def test_the_delivery_mail_job_is_declared_and_registered():
    assert "delivery_mail" in jobs.GENERAL_KINDS and jobs.HANDLER_MODULES["delivery_mail"] == "app.delivery"
    assert "delivery_mail" in jobs._handlers


# ------------------------------------------------------------------------------------------------ límite por IP
def test_ip_limit_on_the_public_page(client, env, monkeypatch):
    monkeypatch.setattr(delivery_router, "PAGE_MAX", 3)
    codes = [client.get("/entrega/" + "z" * 43).status_code for _ in range(5)]
    assert codes[:3] == [404, 404, 404] and codes[3:] == [429, 429]


# ------------------------------------------------------------------------------------------------ «¿próximo evento?» → correo a la comercial (plan §12)
def test_next_event_yes_sends_one_mail_to_the_commercial(client, env, mails, db):
    token = _staff_link(client, env["event"])
    assert client.post(f"/entrega/{token}/encuesta", json=_answers()).status_code == 200
    sent = [m for m in mails if m["to"] == "com1@golden.test"]
    assert len(sent) == 1
    assert env["event"].name in sent[0]["subject"] and "próximo evento" in sent[0]["body"] and "En marzo" in sent[0]["body"]
    job = db.query(Job).filter_by(kind="next_event_mail").one()
    assert "com1@golden.test" not in job.payload_json and "marzo" not in job.payload_json          # la cola solo lleva el id del evento


@pytest.mark.parametrize("q8", [{"choice": "No"}, None])
def test_next_event_no_or_blank_sends_nothing(client, env, mails, db, q8):
    token = _staff_link(client, env["event"])
    body = _answers()
    if q8 is None:
        body["answers"].pop("q8_next_event")
    else:
        body["answers"]["q8_next_event"] = q8
    assert client.post(f"/entrega/{token}/encuesta", json=body).status_code == 200
    assert db.query(Job).filter_by(kind="next_event_mail").count() == 0
    assert not [m for m in mails if m["to"] == "com1@golden.test"]


def test_next_event_helpers_are_pure():
    assert delivery.wants_next_event([{"question_id": "q8_next_event", "choice_text": "Sí"}]) is True
    assert delivery.wants_next_event([{"question_id": "q8_next_event", "choice_text": "No"}]) is False
    assert delivery.wants_next_event([]) is False
    mail = delivery.render_next_event_mail(event_name="Feria <b>", client_name="ACME", commercial_name="Ana", comment="<script>x</script>", link="https://app.test/eventos?editar=1")
    assert "<script>" not in mail["html"] and "&lt;script&gt;" in mail["html"] and "Hola Ana:" in mail["text"]
