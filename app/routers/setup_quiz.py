"""«Configurar el evento por cuestionario» (app/setup_quiz.py): leer las preguntas, guardar las respuestas y ver las acciones pendientes.

La configuración del evento NO se guarda por aquí: la cambian los controles de cada sección de Parámetros con el «Guardar cambios» de siempre. Aquí solo van las respuestas
(para recordar cómo se pensó el evento) y el cálculo de lo que todavía falta hacer."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import audit_actions, localmode, personform, setup_quiz
from app.auth import ROLE_HIERARCHY, effective_roles, get_event_for_staff, require_role_excluding
from app.database import get_db
from app.models import StaffUser

router = APIRouter()
_ROLES = require_role_excluding("coordinador", ("comercial",))          # los mismos de la pantalla de Parámetros


def _questions(staff: StaffUser) -> list:
    can_design = personform.env_enabled() and max(ROLE_HIERARCHY[r] for r in effective_roles(staff)) >= ROLE_HIERARCHY["admin"]
    return setup_quiz.questions_for(local_server=localmode.is_local_server(), person_form=can_design)


def _payload(db: Session, event, staff: StaffUser, stored: dict) -> dict:
    qs = _questions(staff)
    answers = setup_quiz.clean_answers(stored.get("answers"), qs)
    st = setup_quiz.collect_state(db, event)
    return {
        "sections": [{"id": s, "title": t} for s, t in setup_quiz.SECTIONS],
        "questions": qs,
        "answers": answers,
        "saved": bool(stored),
        "updated_at": stored.get("updated_at"),
        "actions": setup_quiz.actions(answers, st, event.id) if stored else [],
        "flags": setup_quiz.state_flags(st),
    }


@router.get("/events/{event_id}/setup-quiz")
def get_setup_quiz(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(_ROLES)):
    event = get_event_for_staff(event_id, db, staff)
    return _payload(db, event, staff, setup_quiz.load(db, event.id))


@router.put("/events/{event_id}/setup-quiz")
def put_setup_quiz(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(_ROLES)):
    """Guarda las respuestas. Con `{"clear": true}` las borra (y con ellas las acciones pendientes)."""
    event = get_event_for_staff(event_id, db, staff)
    if data.get("clear"):
        from app.models import AppSetting
        db.query(AppSetting).filter(AppSetting.key == setup_quiz.setting_key(event.id)).delete(synchronize_session=False)
        audit_actions.record(db, staff, "update", "event_setup_quiz", event.id, event.name, "respuestas borradas")
        db.commit()
        return _payload(db, event, staff, {})
    answers = setup_quiz.clean_answers(data.get("answers"), _questions(staff))
    stored = setup_quiz.save(db, event.id, answers, staff.username)
    audit_actions.record(db, staff, "update", "event_setup_quiz", event.id, event.name, f"{len(answers)} respuestas")
    db.commit()
    return _payload(db, event, staff, stored)
