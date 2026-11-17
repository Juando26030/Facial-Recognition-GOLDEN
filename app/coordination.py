"""Coordinación de eventos (17-nov-2026): quién puede coordinar un evento, quién asigna coordinadores y quién revisa las legalizaciones.

- **Director de coordinadores** (`auth.DIRECTOR_ROLE`): un coordinador con el rol sumado `dir_coordinadores`. Asigna coordinadores (calendario «Asignar coordinadores») y revisa
  legalizaciones. Los **administradores** (admin y super_admin) pueden lo mismo sin necesitar el rol.
- **Quién puede ser coordinador de un evento**: quien tenga el rol coordinador (principal, secundario o sumado), el de director, o sea administrador. Antes solo los dos primeros."""
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import DIRECTOR_ROLE, effective_roles
from app.models import StaffUser

ASSIGNERS = {DIRECTOR_ROLE, "admin", "super_admin"}          # asignar coordinadores a los eventos
REVIEWERS = ASSIGNERS                                          # revisar (aprobar o devolver) las legalizaciones
COORDINATING = {"coordinador", DIRECTOR_ROLE, "admin", "super_admin"}          # roles con los que se puede ser el coordinador de un evento


def can_assign_coordinators(staff) -> bool:
    return bool(ASSIGNERS & effective_roles(staff))


def can_review_legalizations(staff) -> bool:
    return bool(REVIEWERS & effective_roles(staff))


def can_coordinate(staff) -> bool:
    return bool(COORDINATING & effective_roles(staff))


def coordinator_candidates(db: Session) -> list:
    """Cuentas ACTIVAS que se pueden asignar como coordinador de un evento (no archivadas ni coordinadores temporales), ordenadas por nombre."""
    rows = db.query(StaffUser).filter(
        or_(StaffUser.role.in_(("coordinador", "admin", "super_admin")), StaffUser.secondary_role == "coordinador", StaffUser.extra_roles.like("%coordinador%")),
        StaffUser.is_active == True, StaffUser.archived_at.is_(None), StaffUser.event_only.is_(False),  # noqa: E712
    ).all()
    return sorted((s for s in rows if can_coordinate(s)), key=lambda s: ((s.full_name or s.username).lower(), s.id))      # el LIKE solo preselecciona; la pertenencia exacta la decide can_coordinate


def find_coordinator(db: Session, staff_id) -> "StaffUser | None":
    """La cuenta con ese id si se puede asignar como coordinador de un evento; si no, None."""
    if staff_id is None:
        return None
    return next((s for s in coordinator_candidates(db) if s.id == staff_id), None)
