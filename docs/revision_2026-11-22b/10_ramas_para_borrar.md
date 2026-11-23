# 10 · Ramas para borrar: propuesta (23-nov-2026, Fase 6 punto 7)

Solo lectura: no se borró, empujó ni commiteó nada. `origin/main` = `63ec73c` (23-nov); `origin/saas/revision-integral` = `9f29723` (main es ancestro de saas; saas lleva 55 commits más). Método: `git merge-base --is-ancestor`, `git cherry` contra main y contra saas, y `grep` en CHANGELOG, docs, scripts, deploy y workflows.

- **Propios**: commits de la rama que no están en main ni en saas por historial. **Sin equiv.**: de esos, los que no tienen parche equivalente en NINGUNA de las dos (el trabajo que se perdería). **Refs**: archivos que nombran la rama (sin contar esta tabla ni la propuesta 02/14).
- **segura** = todo su contenido ya está en main o en saas (ancestro o parche equivalente; lo «en saas» solo vale al fusionar saas a main). **no borrar** = referida o con papel vivo. **revisar** = tiene commits sin equivalente.

Resumen (104 ramas, sin main ni saas): segura 72, revisar 25, no borrar 7. Ya no existen los grupos A y B (borrados con etiqueta `archivo/…`). Los grupos C1, C2 y D quedan en esta tabla; los ocho `feat/*`/`fix/*`/`ux/guardado-unificado` del 18-nov comparten 8 commits sin equivalente (una revisión sirve para todas).

| Rama | Último commit | Asunto | Propios | Sin equiv. | Refs | Clase | Nota |
|---|---|---|---|---|---|---|---|
| `archivo/corte-main-b5f861b` | 2026-10-05 | corte: main despliega producción en Cloud Run y ya no dispa | 1 | 0 | 1 | **no borrar** | archivo del 0B |
| `archivo/ramas-borradas-0b-2026-11-02` | 2026-11-02 | Archivo: puntas de ramas borradas en la limpieza 0B (2-nov-2 | 9 | 0 | 1 | **no borrar** | archivo del 0B |
| `diag/inventario-base` | 2026-11-22 | Documento consolidado de reglas inamovibles y decisiones (22 | 0 | 0 | 2 | **no borrar** | citada por diag.yml (exclusión explícita) |
| `feat/inventario-base` | 2026-11-22 | Registro: lo elegido se ve completo en cualquier ancho (nomb | 0 | 0 | 2 | **no borrar** | staging actual |
| `fix/legal-1-1-borrador` | 2026-10-05 | Legal (BORRADOR, versión 1.1 pendiente de revisión): apart | 1 | 1 | 4 | **no borrar** | borrador legal pendiente de la auditora (docs/16 B8) |
| `fix/offline-recarga` | 2026-10-05 | Prueba contingency_list_check: la búsqueda por cédula espe | 3 | 2 | 6 | **no borrar** | dependencia de B8 (citada en 6 archivos) |
| `migra/fase1-2` | 2026-11-05 | Quita el símbolo ⌘ de los comentarios (la prueba de ícon | 0 | 0 | 27 | **no borrar** | disparador ya quitado de cloudrun.yml (punto 8, sin commitear); borrar solo tras fusionar ese cambio; sigue en deploy/gcp/config.sh y docs |
| `candidato/produccion-25oct` | 2026-10-26 | Candidato a produccion 25-oct: contenido de migra/fase1-2 ec | 3 | 2 | 3 | **revisar** | 2 commits sin equivalente en main ni saas |
| `diag/verde` | 2026-11-21 | diag: segunda vuelta | 3 | 2 | 0 | **revisar** | 2 commits sin equivalente en main ni saas |
| `docs/fase-1-5-plan` | 2026-11-05 | Plan Fase 1.5: avance de la Ola 0 | 3 | 3 | 0 | **revisar** | 3 commits sin equivalente en main ni saas |
| `feat/disenador-movil` | 2026-11-18 | Diseñador de escarapelas (pantalla pequeña/celular): lienz | 49 | 8 | 0 | **revisar** | 8 commits sin equivalente en main ni saas |
| `feat/flujo-categoria` | 2026-11-18 | Categorías: flujos por categoría (reconocimiento facial, e | 45 | 8 | 0 | **revisar** | 8 commits sin equivalente en main ni saas |
| `feat/formulario-categoria` | 2026-11-18 | Una sola categoría por persona: selector de categoría en r | 39 | 8 | 0 | **revisar** | 8 commits sin equivalente en main ni saas |
| `feat/preimpresion-estado` | 2026-11-18 | Diseñador de escarapelas: más alto para el lienzo (cabecer | 47 | 8 | 0 | **revisar** | 8 commits sin equivalente en main ni saas |
| `feat/prueba-lector-cedula` | 2026-11-19 | Cédula nueva: los nombres salían vacíos cuando el OCR per | 14 | 2 | 0 | **revisar** | 2 commits sin equivalente en main ni saas |
| `feat/vcard-ruleta-calendario` | 2026-11-10 | Documenta el bloque C de la Fase 10 (QR vCard, ruleta, calen | 3 | 1 | 0 | **revisar** | 1 commits sin equivalente en main ni saas |
| `fix/formulario-persona-interruptor` | 2026-11-18 | Formulario de persona: con el interruptor apagado no se mues | 51 | 8 | 0 | **revisar** | 8 commits sin equivalente en main ni saas |
| `fix/nombre-item-zonas` | 2026-11-18 | Parámetros: el nombre de zonas e ítems de inventario vuelv | 48 | 8 | 0 | **revisar** | 8 commits sin equivalente en main ni saas |
| `fix/obligatorios-categoria` | 2026-11-18 | Formulario por categoría: cédula y nombres no se marcan ob | 50 | 8 | 0 | **revisar** | 8 commits sin equivalente en main ni saas |
| `fix/variantes-nombre` | 2026-11-11 | Editor de formularios: el nombre de cada variante se ve pleg | 5 | 1 | 0 | **revisar** | 1 commits sin equivalente en main ni saas |
| `hotfix/estadisticas-registro-2026-11-23` | 2026-11-23 | Hotfix estadísticas: contar sobre toda la base, solo regist | 1 | 1 | 1 | **revisar** | 1 commits sin equivalente en main ni saas |
| `legalizaciones/formato-excel` | 2026-11-14 | Legalizaciones: modelo de datos y migración 0131 (aditiva) | 2 | 1 | 0 | **revisar** | 1 commits sin equivalente en main ni saas |
| `legalizaciones/sobre-crm` | 2026-11-18 | Legalizaciones: duplicar gastos, ordenar arrastrando y alime | 1 | 1 | 1 | **revisar** | 1 commits sin equivalente en main ni saas |
| `producto/1a-pr3-autoimpresion-4a` | 2026-11-03 | PR3: restaurar la línea literal de registeredOrSay y actual | 2 | 2 | 0 | **revisar** | 2 commits sin equivalente en main ni saas |
| `producto/eventos-flujo` | 2026-11-02 | historial: pendiente de CORS para staging.golden-eventos.com | 1 | 1 | 4 | **revisar** | 1 commits sin equivalente en main ni saas |
| `producto/impresion-ajustes` | 2026-10-24 | Prueba: con red intermitente el pedido de impresión se rein | 9 | 2 | 3 | **revisar** | 2 commits sin equivalente en main ni saas |
| `ux/almacen` | 2026-11-17 | Almacén: mismo estilo que el resto de la app y guardado uni | 2 | 1 | 1 | **revisar** | 1 commits sin equivalente en main ni saas |
| `ux/evento` | 2026-11-17 | Plantilla de evento: el color de las categorías queda pendi | 7 | 1 | 1 | **revisar** | 1 commits sin equivalente en main ni saas |
| `ux/fase-1-7` | 2026-11-06 | Fase 1.7 Ola 0: piezas de puerta en el sistema de diseño (b | 1 | 1 | 3 | **revisar** | 1 commits sin equivalente en main ni saas |
| `ux/fase1-visual` | 2026-10-18 | UX: los estilos de los íconos (.ux-icon) pasan de ux1.css a | 8 | 8 | 4 | **revisar** | 8 commits sin equivalente en main ni saas |
| `ux/guardado-unificado` | 2026-11-18 | Formulario de persona: con el interruptor apagado no se mues | 51 | 8 | 0 | **revisar** | 8 commits sin equivalente en main ni saas |
| `ux/inventario` | 2026-11-17 | Administrar catálogo: renombrar categorías y editar un pro | 4 | 3 | 1 | **revisar** | 3 commits sin equivalente en main ni saas |
| `candidato/produccion-28oct` | 2026-10-28 | Producción: modo sin conexión (contingencia) ENCENDIDO — | 0 | 0 | 4 | **segura** | ancestro de main (todo en main) |
| `candidato/produccion-29oct` | 2026-10-28 | Paquete de producción 29-oct: apunta al hash de staging con | 0 | 0 | 4 | **segura** | ancestro de main (todo en main) |
| `chore/0b-calidad` | 2026-11-02 | 0B calidad: ruff revisa TODO el repo en el CI + pre-commit o | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `chore/0c-escaneres` | 2026-11-02 | 0C: escáneres gratuitos en el CI (gitleaks, pip-audit, Band | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `crm/importar-volcado` | 2026-11-12 | CRM: estados de cuenta de SuiteCRM, categoría/tipo/industri | 2 | 0 | 0 | **segura** | 2 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `docs/0b-indice-y-heredado` | 2026-11-02 | 0B: índice de docs/, deploy/LEEME.md (vigente vs heredado d | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `docs/0c-cierre` | 2026-11-03 | 0C: informe de cierre (altos 0, ZAP completo 0 fallos) | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `docs/0c-hallazgos` | 2026-11-02 | 0C: hallazgos de la pasada 2 (ronda cruzada del equipo rojo) | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `docs/estandares-visuales` | 2026-11-04 | Docs: estándares visuales unificados, tablero del plan al d | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `f5/a-facturado` | 2026-11-09 | Fase 5 A: pruebas de Facturado y base final, documentación | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `f5/b-encuesta` | 2026-11-09 | Fase 5 B: entrega al cliente con encuesta de satisfacción y | 0 | 0 | 2 | **segura** | ancestro de main (todo en main) |
| `f5/base` | 2026-11-09 | Merge remote-tracking branch 'origin/f4/integracion' into f5 | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `f5/c-jornada` | 2026-11-09 | Jornada: pruebas (pytest y JS), fixture regenerado y docs/FA | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `f5/d-inventario` | 2026-11-09 | Inventario: pantalla del catálogo en Configuración, bloque | 0 | 0 | 2 | **segura** | ancestro de main (todo en main) |
| `f5/e-historial` | 2026-11-09 | Fase 5 E: historial de cambios del evento por campo y correo | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `f6/a-descargar` | 2026-11-09 | Fase 6 (A): lista de eventos de la nube en el servidor local | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `f6/b-token` | 2026-11-09 | Fase 6 (B): subida del servidor local a la nube cada 30 min, | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `f6/c-cuentas` | 2026-11-09 | Fase 6: sincronizar cuentas nube->local (hash, altas/bajas/r | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `f6/d-instalador` | 2026-11-09 | Fase 6: instalador nativo de Windows (Inno Setup, servicios, | 0 | 0 | 2 | **segura** | ancestro de main (todo en main) |
| `f7/url-limpia` | 2026-11-09 | URL limpia: edición en el modal del evento, pruebas y docs/ | 0 | 0 | 2 | **segura** | ancestro de main (todo en main) |
| `f8/7-cobros` | 2026-11-09 | Fase 8.7: cuentas de cobro de Wompi de terceros (multi-cuent | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `feat/1a-buscador-unico` | 2026-11-04 | Merge branch 'main' into feat/1a-buscador-unico | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `feat/1a-carga-flexible` | 2026-11-04 | Seguridad de la carga: topes en dup_offsets y en la etiqueta | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `feat/1a-cola-compartida` | 2026-11-04 | Merge branch 'main' into feat/1a-cola-compartida | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `feat/cobros-gastos` | 2026-11-10 | Cadena de migraciones: 0126 (bloque D) sigue a 0124 (bloque  | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `feat/cupo-cerrado` | 2026-11-04 | Cupos: máximo 0 = cerrado temporalmente (se guarda, deshabi | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `feat/evento-compartido-nube` | 2026-11-21 | Documentación: evento compartido y «Usará servidores loca | 0 | 0 | 3 | **segura** | ancestro de main (todo en main); línea/marcador de producción: etiquetar antes |
| `feat/menu-ocultable` | 2026-11-18 | Menú lateral (Clientes, CRM, Eventos…): botón para ocult | 1 | 0 | 0 | **segura** | 1 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `feat/preimpresion` | 2026-11-18 | Preimpresiones: filtro con lista de valores de la base (no s | 1 | 0 | 0 | **segura** | 1 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `feat/subcategorias-codigo` | 2026-11-12 | fix: guard de base archivada en la plantilla de carga y 0141 | 1 | 0 | 0 | **segura** | 1 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `fix/0c-altas` | 2026-11-02 | 0C: corrige pruebas y deja nombre/rol/entidad actualizables  | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `fix/0c-d9-integrity` | 2026-11-03 | 0C-D9: integrity en SheetJS 0.18.5 y Chart.js 4.5.1 | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `fix/0c-dependencias` | 2026-11-02 | 0C: actualiza cryptography, pillow, dnspython y setuptools ( | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `fix/0c-escaneres-limpios` | 2026-11-04 | Fusiona main en fix/0c-escaneres-limpios (conflicto solo en  | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `fix/0c-lote2-a` | 2026-11-03 | 0C-C11: politica de contrasenas al crear o restablecer perso | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `fix/0c-lote2-b` | 2026-11-03 | Pruebas: ajustar a deploy_service con nombre corto y a la ca | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `fix/0c-lote2-c` | 2026-11-03 | Ruff: importación duplicada en api.py | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `fix/0c-medios` | 2026-11-02 | 0C medios (lote 1): formulas de Excel neutralizadas, SECRET_ | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `fix/0c-retest` | 2026-11-02 | 0C: Permissions-Policy y HSTS; staging nunca recibe credenci | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `fix/0c-setuptools` | 2026-11-03 | 0C: vuelve a setuptools 69.5.1 (pkg_resources es necesario p | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `fix/descarga-archivos-digitador` | 2026-11-12 | Editar persona: digitador (cliente temporal y digitador temp | 1 | 0 | 0 | **segura** | 1 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `fix/local-eventos-vista` | 2026-11-12 | Instalador desde Linux: Inno Setup tambien debe poder leer e | 5 | 0 | 0 | **segura** | 5 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `fix/precarga-variantes` | 2026-11-10 | Hotfix: subir la imagen de a una capa (connection refused en | 4 | 0 | 1 | **segura** | 4 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `fix/wipe-bloqueo-entorno` | 2026-11-11 | Bloqueo por entorno en scripts/wipe_all_data.py (lista de lo | 1 | 0 | 0 | **segura** | 1 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `hotfix/estadisticas-prod-2026-11-23` | 2026-11-23 | Hotfix estadísticas sobre la línea de producción (03679cb | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `hotfix/subida-formulario-2026-11-21` | 2026-11-21 | HOTFIX formulario público: la subida de archivos copia el a | 0 | 0 | 3 | **segura** | ancestro de main (todo en main); línea/marcador de producción: etiquetar antes |
| `integracion/legalizaciones-reporte` | 2026-11-18 | Merge staging/integrada (CRM 0153/0154) y renumerar la migra | 2 | 0 | 0 | **segura** | 2 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `local/ejecutable-2026-11-18` | 2026-11-19 | Formularios con reenvio: la inscripcion repetida sale marcad | 1 | 0 | 0 | **segura** | 1 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `prep/main-al-dia` | 2026-11-22 | Poner main al día: fusiona feat/evento-compartido-nube (lí | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `prod/llaves-escaner-2026-11-20` | 2026-11-20 | Servidor local: /certificado para quitar el aviso «No segur | 0 | 0 | 3 | **segura** | ancestro de main (todo en main); línea/marcador de producción: etiquetar antes |
| `prod/qr-inventario-digital` | 2026-11-18 | Legalizaciones: duplicar gastos, ordenar arrastrando y alime | 3 | 0 | 0 | **segura** | 3 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `producto/1a-base-diseno` | 2026-11-03 | Prueba del login: ?v= exigido a todo estático, no solo a st | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `producto/1a-pr1-medicion` | 2026-11-03 | 1A-PR1: el cronómetro no pisa el escuchador de «input» de | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `producto/1a-pr2-search-core` | 2026-11-03 | Buscador único: cédula predictiva también sin red (cedula | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `producto/ahorro-neon` | 2026-11-03 | Ahorro de Neon: nunca apagar jamás (-1), CU mínimo 0,25, v | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `producto/constancia-puerta` | 2026-10-21 | Constancia en la puerta: tras registrar la aceptación se av | 0 | 0 | 2 | **segura** | ancestro de main (todo en main) |
| `producto/sesion-exencion-acotada` | 2026-11-03 | Sesión: la exención por inactividad solo rige con impresi | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `sec/a-local` | 2026-11-09 | F5-9 A: informe de la revisión de seguridad del servidor lo | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `sec/b-publico` | 2026-11-09 | Seguridad F5-9 B (público sin sesión): autorregistro no su | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `sec/c-pagos` | 2026-11-09 | Seguridad F5-9 C1-C5: pagos de Wompi multicuenta | 0 | 0 | 2 | **segura** | ancestro de main (todo en main) |
| `sec/d-eventos` | 2026-11-09 | Seguridad F5-9 D: almacén/contabilidad solos no abren datos | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `sec/e-plataforma` | 2026-11-09 | Seguridad F5-9 E: paneles de gastos solo para personal globa | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |
| `staging/integracion-mas-p2` | 2026-11-17 | Solo STAGING: integracion/legalizaciones-reporte + almacen/p | 1 | 0 | 0 | **segura** | 1 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `staging/integrada` | 2026-11-19 | Formularios con reenvio: la inscripcion repetida sale marcad | 1 | 0 | 0 | **segura** | 1 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `staging/integrada-0156` | 2026-11-18 | Integra staging/integrada (legalizaciones, director de coord | 3 | 0 | 0 | **segura** | 3 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `staging/lector-cedula` | 2026-11-19 | Carga: las filas audit_* del evento se conservan y se inform | 31 | 0 | 0 | **segura** | 31 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `ux/admin` | 2026-11-17 | Supereventos: filas con componentes .gw-card-row en vez de e | 8 | 0 | 1 | **segura** | 8 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `ux/base` | 2026-11-17 | docs/ux: guardado unificado y estilo común — encargo y re | 1 | 0 | 2 | **segura** | 1 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `ux/cargas` | 2026-11-09 | Carga visible (6): guía docs/ux/CARGAS_Y_ESQUELETOS.md (có | 0 | 0 | 0 | **segura** | ancestro de main (todo en main) |
| `ux/crm` | 2026-11-17 | CRM · productos y plantillas: avisos al activar/archivar y  | 7 | 0 | 1 | **segura** | 7 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `ux/kiosk` | 2026-11-17 | Legalizaciones: el encabezado se guarda con la barra única  | 3 | 0 | 1 | **segura** | 3 commits propios, todos con parche equivalente en main o saas (0 sin equivalente en main sola) |
| `vis/f5-9` | 2026-11-09 | Revisión visual F5-9 (6): Cuentas de cobro sin desborde en  | 0 | 0 | 1 | **segura** | ancestro de main (todo en main) |

## Hotfix y diag
- `hotfix/estadisticas-prod-2026-11-23` y `hotfix/subida-formulario-2026-11-21`: ancestros de main, seguras (etiquetar la segunda antes: fue la línea de producción).
- `hotfix/estadisticas-registro-2026-11-23`: 1 commit (`7e22d1d`) sin equivalente; es el mismo arreglo que `dd6db3c` (ya en main) sobre otra base. Revisar a ojo antes de borrar.
- `diag/verde`: 3 commits del 21-nov sin equivalente (las 47 pruebas que fallan, segunda vuelta, merge): revisar. `diag/inventario-base`: conservar (`diag.yml` la excluye por nombre).

## Propuesta de comandos — NO ejecutar sin su sí (Juan David decide)
Solo ramas «segura». Primero etiqueta `archivo/<rama>` en el SHA (como en 0B; recuperar: `git branch <rama> <etiqueta>`), luego borrar.

```bash
# NO ejecutar sin su sí
for b in candidato/produccion-28oct candidato/produccion-29oct chore/0b-calidad chore/0c-escaneres crm/importar-volcado docs/0b-indice-y-heredado docs/0c-cierre docs/0c-hallazgos docs/estandares-visuales f5/a-facturado f5/b-encuesta f5/base f5/c-jornada f5/d-inventario f5/e-historial f6/a-descargar f6/b-token f6/c-cuentas f6/d-instalador f7/url-limpia f8/7-cobros feat/1a-buscador-unico feat/1a-carga-flexible feat/1a-cola-compartida feat/cobros-gastos feat/cupo-cerrado feat/evento-compartido-nube feat/menu-ocultable feat/preimpresion feat/subcategorias-codigo fix/0c-altas fix/0c-d9-integrity fix/0c-dependencias fix/0c-escaneres-limpios fix/0c-lote2-a fix/0c-lote2-b fix/0c-lote2-c fix/0c-medios fix/0c-retest fix/0c-setuptools fix/descarga-archivos-digitador fix/local-eventos-vista fix/precarga-variantes fix/wipe-bloqueo-entorno hotfix/estadisticas-prod-2026-11-23 hotfix/subida-formulario-2026-11-21 integracion/legalizaciones-reporte local/ejecutable-2026-11-18 prep/main-al-dia prod/llaves-escaner-2026-11-20 prod/qr-inventario-digital producto/1a-base-diseno producto/1a-pr1-medicion producto/1a-pr2-search-core producto/ahorro-neon producto/constancia-puerta producto/sesion-exencion-acotada sec/a-local sec/b-publico sec/c-pagos sec/d-eventos sec/e-plataforma staging/integracion-mas-p2 staging/integrada staging/integrada-0156 staging/lector-cedula ux/admin ux/base ux/cargas ux/crm ux/kiosk vis/f5-9; do git tag "archivo/$b" "origin/$b"; done
git push origin --tags

git push origin --delete candidato/produccion-28oct candidato/produccion-29oct chore/0b-calidad chore/0c-escaneres crm/importar-volcado docs/0b-indice-y-heredado
git push origin --delete docs/0c-cierre docs/0c-hallazgos docs/estandares-visuales f5/a-facturado f5/b-encuesta f5/base
git push origin --delete f5/c-jornada f5/d-inventario f5/e-historial f6/a-descargar f6/b-token f6/c-cuentas
git push origin --delete f6/d-instalador f7/url-limpia f8/7-cobros feat/1a-buscador-unico feat/1a-carga-flexible feat/1a-cola-compartida
git push origin --delete feat/cobros-gastos feat/cupo-cerrado feat/evento-compartido-nube feat/menu-ocultable feat/preimpresion feat/subcategorias-codigo
git push origin --delete fix/0c-altas fix/0c-d9-integrity fix/0c-dependencias fix/0c-escaneres-limpios fix/0c-lote2-a fix/0c-lote2-b
git push origin --delete fix/0c-lote2-c fix/0c-medios fix/0c-retest fix/0c-setuptools fix/descarga-archivos-digitador fix/local-eventos-vista
git push origin --delete fix/precarga-variantes fix/wipe-bloqueo-entorno hotfix/estadisticas-prod-2026-11-23 hotfix/subida-formulario-2026-11-21 integracion/legalizaciones-reporte local/ejecutable-2026-11-18
git push origin --delete prep/main-al-dia prod/llaves-escaner-2026-11-20 prod/qr-inventario-digital producto/1a-base-diseno producto/1a-pr1-medicion producto/1a-pr2-search-core
git push origin --delete producto/ahorro-neon producto/constancia-puerta producto/sesion-exencion-acotada sec/a-local sec/b-publico sec/c-pagos
git push origin --delete sec/d-eventos sec/e-plataforma staging/integracion-mas-p2 staging/integrada staging/integrada-0156 staging/lector-cedula
git push origin --delete ux/admin ux/base ux/cargas ux/crm ux/kiosk vis/f5-9
```

`scripts/limpiar_ramas_2026-11-22.sh` hace lo mismo con comprobaciones (pide escribir «BORRAR <grupo>»). Las «revisar» y «no borrar» quedan fuera de este bloque.

## Punto 8 (hecho en local, sin commit)
- `.github/workflows/cloudrun.yml`: quitado el `push: branches: [migra/fase1-2]` (queda solo `workflow_dispatch`) y la condición del job `staging` pasa a `workflow_dispatch` desde `feat/**` o `saas/**`.
- `tests/test_cutover_workflows.py`: la prueba que fijaba la rama ahora exige que NO haya `push`; 4 pruebas en verde (`python3 -m pytest -q --noconftest`).
- Siguen nombrándola (no cambiados): `CLAUDE.md` no (ya sin mención), `deploy/gcp/config.sh` (`STAGING_BRANCH_REF` por defecto), `deploy/gcp/bootstrap.sh:120`, `deploy/LEEME.md:4`, `scripts/borrar_ramas_integradas.sh`, `scripts/limpiar_ramas_2026-11-22.sh` (protegida) y docs históricos (13, 15, 19, HANDOFF, legal/*, revision_2026-11-22/*). Aviso: `config.sh` conserva `migra/fase1-2` como ref de Workload Identity de staging; hay que cambiarlo junto con el vínculo en GCP antes de borrar la rama.
