import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import User, AccessLog, EventAttendee, Event


def _event_directory_users(db: Session, event_id: int, tenant_id: str):
    """Mismo universo que el Directorio/Estadísticas de ESE evento (EventAttendee ∪ AccessLog
    filtrados por event_id) — no todo el tenant. Réplica local de la misma lógica que
    app/routers/stats.py: _event_directory_users, para no cruzar imports entre app/reports.py y
    app/routers/* (capas separadas a propósito en este proyecto)."""
    attendee_ids = {a.user_id for a in db.query(EventAttendee).filter(EventAttendee.event_id == event_id)}
    log_ids = {l.user_id for l in db.query(AccessLog).filter(AccessLog.event_id == event_id)}
    all_ids = attendee_ids | log_ids
    if not all_ids:
        return []
    return db.query(User).filter(User.tenant_id == tenant_id, User.id.in_(all_ids)).all()


class ReportManager:
    @staticmethod
    def generate_excel_report(db: Session, event_id: int, tenant_id: str, output_path: str):
        # Scoping por evento (2026-09-16, corrección real): antes filtraba solo por tenant_id,
        # mezclando en un mismo reporte a personas de TODOS los eventos de este cliente. Ahora usa
        # el mismo universo que el Directorio/Estadísticas de este evento puntual — necesario
        # además para que las columnas de "opcional_N" de abajo signifiquen lo mismo en todas las
        # filas (el mismo opcional_1 puede rotularse distinto en otro evento del mismo cliente).
        event = db.query(Event).filter(Event.id == event_id).first()
        optional_labels = sorted(event.get_optional_labels().items(), key=lambda kv: int(kv[0].split("_")[1])) if event else []

        subquery = db.query(
            AccessLog.user_id,
            func.min(AccessLog.timestamp).label('first_scan')
        ).filter(AccessLog.event_id == event_id).group_by(AccessLog.user_id).subquery()

        first_scan_by_user = {row.user_id: row.first_scan for row in db.query(subquery)}

        data = []
        for user in _event_directory_users(db, event_id, tenant_id):
            first_scan = first_scan_by_user.get(user.id)
            fecha_reg = first_scan.strftime("%Y/%m/%d") if first_scan else ""
            hora_reg = first_scan.strftime("%H:%M:%S") if first_scan else ""

            row = {
                "Nombres": (user.first_name or "").upper(),
                "Apellidos": (user.last_name or "").upper(),
                "Identificación": user.id,
                "Tel. Celular": user.phone or "",
                "E-mail Corporativo": user.email or "",
                "Empresa": (user.company or "").upper(),
                "Cargo": (user.role or "").upper(),
                "Tipo_Pago": "Ninguno",
                "Categoría": "Asistente",
                "Tipo_Registro": "Registro en Punto",
                "Estado": "CargadoBD",
                "FechaRegistro": fecha_reg,
                "HoraRegistro": hora_reg,
                "FechaCreación": fecha_reg,
                "FechaModificación": fecha_reg,
                "Pago_Evento": "FALSO",
                "Detalle_Pago": "",
                "Preinscrito": "FALSO",
                "Diplomas": "0",
                "Escarapelas": "1",
                "ListCiudades2": "",
                "ListDepartamento": "",
                "Tipo de Empresa": user.opt_1 or "",
                "Cantidad de Empl": user.opt_2 or "",
                "Pais": "COLOMBIA",
                "Observaciones": "",
                "Jerarquia del Cargo": "",
                "VIP": "NO",
                "usuario": "digitador.temp4",
            }
            extras = user.get_extras()
            for key, label in optional_labels:
                row[label] = extras.get(key, "")
            data.append(row)

        df = pd.DataFrame(data)
        df.to_excel(output_path, index=False, engine='openpyxl')
        return output_path