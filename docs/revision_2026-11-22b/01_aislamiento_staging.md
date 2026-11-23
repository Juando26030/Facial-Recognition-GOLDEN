# Fase 4 — Aislamiento entre clientes en staging (23-nov-2026)

Staging (`goldenweb-staging`, commit `c58fef7`) con `ENFORCE_STAFF_TENANT=1` y `ENFORCE_STAFF_EVENT_SCOPE=1` (solo staging, desde `deploy/gcp/deploy.sh`; producción sigue en «0»).
Cuenta ficticia: empresa «PRUEBA Empresa Ficticia» (plan Básico) y su administrador `prueba_admin` (rol admin, cliente propio). Datos inventados.

## Lo que se comprobó, con la sesión de la cuenta ficticia (solo conteos, ningún dato personal copiado)
| Prueba | Resultado |
|---|---|
| Crear empresa y su administrador | Bien; con el aislamiento apagado el botón estaba bloqueado (como dice docs/27). La contraseña temporal se muestra una vez. |
| `/plataforma`, `/api/platform/*`, `/api/server-keys`, CRM, Gastos | 403 / redirección. Cerrado. |
| `/api/events`, `/api/staff`, `/api/staff/assignable`, `/api/payment-accounts` | Listas vacías. Cerrado. |
| `/api/events/<id>` (ids 1-42 de Golden) y 12 rutas hijas, y `/kiosk/<id>…` | 404 / redirección para Golden, 200 para el evento propio. Cerrado. |
| Exportaciones de clientes y digitadores | Ya filtradas en el código. |
| Límite del plan (1 evento al mes) | Primer evento creado; el segundo: 403 «Tu plan permite 1 evento por mes; contacta a soporte». Bien. |

## Filtraciones encontradas (todas con el aislamiento ENCENDIDO)
| # | Ruta | Qué veía la cuenta ajena | Corrección |
|---|---|---|---|
| 1 | `GET /api/staff/coordinators` | 8 personas de Golden (usuario y nombre) | filtro por cliente (`3e34bcb`) |
| 2 | `GET /api/staff/commercials` | 3 personas de Golden | idem |
| 3 | `GET /api/nodes` | 3 servidores locales de Golden | idem |
| 4 | `GET /api/payment-accounts-forms` | 23 eventos y 18 formularios de Golden | idem |
| 5 | `GET /api/system-alerts` | destinatarios, personal elegible (12) y avisos de Golden | 403 para cuentas ajenas |
| 6 | `POST /api/events` | aceptó como «comercial» a una persona de Golden | validación por cliente al crear y editar (`10e633e`) |

Pruebas de texto: `tests/test_aislamiento_listas_2026_11_23.py` (6).

**Re-verificado en staging (`b0cc145`, misma cuenta ficticia):** coordinadores 1 (solo ella misma), comerciales 0, servidores 0, formularios/eventos 1/1 (los propios), alertas 403. Las filtraciones 1-5 quedaron cerradas. La 6 (asignar comercial de Golden) no se pudo repetir en vivo porque el plan Básico ya agotó su evento del mes; queda cubierta solo por la prueba de texto.

## Lo que sigue abierto (plan, no improvisado)
- **Catálogos globales sin dueño por empresa:** almacén (productos, unidades, novedades), catálogo de inventario, tipos de evento, estados y plantilla de evento se ven iguales para todas las empresas. Decidir si son de la plataforma (compartidos) o de cada empresa.
- **Una empresa nueva no puede crear eventos si la plantilla exige «comercial asignada»** hasta que cree su propia cuenta comercial (con la corrección 6 ya no puede usar la de Golden). Falta una guía en pantalla (`¿Qué sigue?`).
- El barrido por rutas fue manual (~120 rutas GET sin parámetro + ~15 con id de evento). El filtro por empresa en TODAS las consultas y RLS sigue siendo la obra grande (160-220 h, reporte 01 Anexo A.3).
- No probado: rutas POST/PUT/DELETE cruzadas entre empresas; solo lectura.
