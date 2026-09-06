import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import User, AccessLog

class ReportManager:
    @staticmethod
    def generate_excel_report(db: Session, tenant_id: str, output_path: str):
        # Subconsulta: Obtenemos solo el primer escaneo/registro de cada usuario para evitar filas duplicadas
        subquery = db.query(
            AccessLog.user_id,
            func.min(AccessLog.timestamp).label('first_scan')
        ).filter(AccessLog.tenant_id == tenant_id).group_by(AccessLog.user_id).subquery()
        
        # Cruzamos la tabla de usuarios únicos con su primera fecha de acceso
        query = db.query(User, subquery.c.first_scan).outerjoin(
            subquery, User.id == subquery.c.user_id
        ).filter(User.tenant_id == tenant_id)
        
        data = []
        for user, first_scan in query.all():
            # Separación básica de Nombres y Apellidos
            nombres_apellidos = user.name.split(" ", 1) if user.name else ["", ""]
            nombre = nombres_apellidos[0]
            apellido = nombres_apellidos[1] if len(nombres_apellidos) > 1 else ""
            
            fecha_reg = first_scan.strftime("%Y/%m/%d") if first_scan else ""
            hora_reg = first_scan.strftime("%H:%M:%S") if first_scan else ""
            
            data.append({
                "Nombres": nombre.upper(),
                "Apellidos": apellido.upper(),
                "Identificación": user.id,
                "Tel. Celular": user.phone or "",
                "E-mail Corporativo": user.email or "",
                "Empresa": (user.company or "").upper(),
                "Cargo": (user.role or "").upper(),
                "Tipo_Pago": "Ninguno",
                "Categoría": "Asistente",
                "Tipo_Registro": "Registro en Punto",
                "Estado": "Nuevo",
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
                "usuario": "sistema"
            })
            
        df = pd.DataFrame(data)
        df.to_excel(output_path, index=False, engine='openpyxl')
        return output_path