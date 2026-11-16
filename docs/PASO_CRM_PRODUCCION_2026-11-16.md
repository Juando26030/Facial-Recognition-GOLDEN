# CRM en producción + importación de SuiteCRM (16-nov-2026)

Autorizado por Juan David (16-nov-2026, 13:05): encender el CRM en producción e importar todo SuiteCRM. La auditora ya recibió el aviso y lo aprobó (dicho por Juan David). Archivos CSV convertidos del volcado: en el computador de Juan David.

Respaldo de Neon hecho antes: rama `antes-crm-produccion-16nov` (vence 23-nov).
Estado verificado en producción antes de empezar: 6 clientes, ningún `client_code` numérico, usuario `lyz.velandia` (rol comercial) existe, tablas `crm_*` creadas por la migración 0130-0145.

## Orden
1. **Contador `account`** (antes de encender): `scripts/crm_set_counter.py --name account --floor 181111 --apply` (181111 = mayor código de cuenta de SuiteCRM; en producción no hay `client_code` numérico). El importador sube después los de oportunidad/cotización/proforma.
2. **Despliegue** con `CRM_ENABLED=1 CRM_IMPORT_APPLY=1 CRM_IMPORT_OWNER_USERNAME=lyz.velandia FORCE=1` (hay eventos en curso; Juan David ya autorizó FORCE para esta tanda).
3. `/sistema`: chequeo «CRM» en verde.
4. **Importar** en `/crm/importar` (admin): subir los 7 CSV → Muestra → Prueba completa → «Cargar de verdad» (escribir CARGAR). Parejas clientes↔cuentas: solo se aplican las aprobadas.
5. **Apagar la carga real:** `gcloud run services update golden-web --region us-east4 --project goldenweb-prod --update-env-vars CRM_IMPORT_APPLY=0` (el CRM sigue encendido).
6. Verificar conteos contra `docs/crm/IMPORTACION_VOLCADO.md` (cuentas 3.666 · contactos 9.116 · oportunidades 22.274 · actividades 21.279 · cotizaciones 21.575 / 61.098 líneas · productos 366).

## Vuelta atrás
`CRM_ENABLED=0` (redeploy o `--update-env-vars`) apaga el CRM sin tocar la base. Datos: restaurar desde la rama `antes-crm-produccion-16nov` (decisión aparte).
