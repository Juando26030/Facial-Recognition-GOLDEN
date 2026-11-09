# Revisión 9-nov-2026 · Lo planeado contra lo construido (Fases 5 a 9)

Fuente del plan: `docs/29_PLAN_MAESTRO_ETAPA_2026-10-29.md` (§10–§14) y las decisiones de cada fase (`docs/FASE_5_DECISIONES.md`, `docs/FASE_6_SERVIDOR_LOCAL.md`, `docs/FASE_8_*.md`, `docs/FASE_9_PLATAFORMA.md`, docs 20–24).
Código revisado: rama `f5/integracion` contra producción (`2c8c4d7`). Nada de esto se ha probado con base de datos (la suite corre el 11-nov en Cloud Shell).

Leyenda: ✅ construido · ⚠️ construido con un hueco · ❌ no construido · ⏸️ excluido por decisión de Juan David

## Fase 5 · Crear y configurar eventos
| Punto del plan | Estado | Nota |
|---|---|---|
| Asistente de creación por pasos | ✅ | `templates/nuevo_evento.html` (pasos definidos por la plantilla). |
| Ficha configurable por el admin (plantilla) | ✅ | `app/event_template.py`. Tipos de evento salen de la plantilla (decisión 8-nov). |
| Jornada calculada (media, intermedia, completa, extendida) | ✅ | `app/workday.py`; es un campo más de la plantilla. Límites 6/9/12 h «por confirmar». |
| Estados del admin con reglas | ✅ | `app/event_rules.py`; «Facturado» con regla `client_delivery`. |
| Historial por campo y correo por campos clave a comercial, coordinador, almacén y contabilidad | ✅ | `app/event_history.py` (campo clave = obligatorio en la plantilla). |
| Inventario con catálogo, cuadre exacto para pasar a «En proceso» | ✅ | `app/inventory_svc.assert_can_enter_in_progress`; se puede apagar con `INVENTORY_BALANCE_GATE=0`. |
| Reserva 1 día antes (misma ciudad) / 7 días (otra ciudad) | ✅ | `app/inventory_alerts.py` (bodega = `INVENTORY_HOME_CITY`, Bogotá por defecto). |
| Facturado solo desde Finalizado y con base final | ✅ | `docs/FASE_5_FACTURADO.md`. |
| Entrega al cliente: enlace + encuesta + descarga de la base final | ✅ | `app/delivery.py`, `/entrega/<token>`. |
| Roles almacén y contabilidad | ✅ | Cuentas propias o combinadas; entran a `/inventario`. |
| Exportar/importar evento con lo nuevo | ⚠️ | El paquete NO lleva: inventario de catálogo (`event_inventory_items`), historial de cambios, base final, facturado, turnos, expositores ni encuesta. Ver Fase 6. |

## Fase 6 · Operación sin red
| Punto del plan | Estado | Nota |
|---|---|---|
| E1 bajar el evento al servidor local | ✅ sin probar | Usa el paquete de exportar evento. |
| E2 arrendamiento, subida cada 30 min, «Pasar a internet», cuentas nube→local, «Actualizar ahora» | ✅ sin probar | `app/node_sync.py`, `app/event_lease.py`, `app/account_sync.py`, `app/local_update.py`. |
| **«Listo cuando: el evento se atiende sin internet y al conectarse queda IGUAL en la nube»** | ⚠️ **hueco, contenido** | La subida solo manda **personas nuevas** e **ingresos**. NO suben: ediciones de personas, entregas de inventario, movimientos de áreas, impresiones, ruleta, turnos, contactos de expositores, aceptaciones/firmas. **Contención (9-nov):** «Pasar a internet» ya NO libera el evento si existe algo así (se ve en `/sincronizacion`; válvula `NODE_RELEASE_ALLOW_LOCAL_ONLY=1`). Ampliar la subida queda para E3/E4. |
| E3 R4 PIN / exportación de emergencia y R2 foto y consentimiento sin red | ❌ | Por programar (orden decidido: R4 antes de R2). |
| E4 R3 edición sin red con conflictos y R5 dos dispositivos | ❌ | Por programar. |
| Instalador de Windows | ✅ sin probar | Requiere prueba en un Windows real. |
| Ensayo en campo con computador | ❌ | Pendiente. |

## Fase 7 · Cliente y marca
| Punto del plan | Estado | Nota |
|---|---|---|
| Registro touch | ⏸️ | Juan David: «no quiero que cambien al registro Touch por ahora». |
| Logo y color por evento | ✅ | Ya existía (confirmado por Juan David). |
| URL limpia de inscripciones | ✅ | `app.golden-eventos.com/inscripciones/...`; falta definir `PUBLIC_FORMS_BASE_URL` al desplegar. |
| Liberación al cliente: facturado + encuesta para descargar | ✅ | Se hizo dentro de la Fase 5 (B). |
| Correo de alerta a la comercial si el cliente marca interés en otro evento | ✅ (9-nov) | Faltaba; se construyó en la revisión: «Sí» en la pregunta 8 → correo `next_event_mail` a la comercial del evento. |

## Fase 8 · Vanguardia
| Punto del plan | Estado | Nota |
|---|---|---|
| Pantalla de TV y estadísticas móviles | ✅ | `/kiosk/{id}/tv` y `/ver/tv/<token>`. |
| Turnos y filas | ✅ | Pendiente opcional: QR en la escarapela que abra el turno directo. |
| Autoregistro en el kiosco | ✅ | Pendiente legal: aviso literal de la auditora. |
| QR dinámico y Wallet | ✅ | Wallet solo aparece con credenciales de Google/Apple (no configuradas). El pase de Wallet lleva el QR estático firmado. |
| WhatsApp y SMS | ⏸️ | Excluido: solo correos. |
| Contactos para expositores | ✅ | QR y NFC (escritura NFC solo Chrome Android). Pendiente legal: revisar el texto de consentimiento `v1.0_contacto`. |
| Pagos con QR | ✅ | QR de la página del formulario o de un *Payment Link* de Wompi; cuentas de terceros. El QR nativo Bancolombia no tiene API verificada. |

## Fase 9 · Plataforma y legal
| Punto del plan | Estado | Nota |
|---|---|---|
| Copias a las 3 a. m. | ✅ verificado | Diarias del 1 al 9-nov en el bucket; trabajo horario sin errores. |
| Alerta de borrado masivo | ✅ sin probar | Destinatarios configurables en Configuración. |
| Copia semanal fuera del proyecto | ✅ sin probar | SharePoint «Respaldos GoldenWeb», carpeta «Base de datos». Secretos creados el 9-nov. |
| Copia fuera de línea de la llave + `--version-destroy-ttl=7d` | ✅ hecho | Llave en el gestor; retraso de 7 días en 3 secretos. |
| Política de privacidad v1.1 | ⏸️ | «Eso está quieto». |
| Marcador de proveedores → panel de gastos | ✅ sin probar | Cambiado por Juan David a panel de gastos + análisis de eventos. La importación de costos de Google usaba una librería que no estaba en la imagen; se cambió por la API REST (informe de seguridad E, E-6). Falta dar permisos de BigQuery a la cuenta del Job de operaciones. |

## Cosas de esta revisión que requieren decisión de Juan David
1. **Servidor local (Fase 6):** se aplicó el bloqueo (decisión por defecto, reversible). Queda por decidir cuándo se amplía la subida (E3/E4) para usarlo en eventos con inventario, turnos, expositores o impresión.
2. **Correo de «próximo evento»:** construido hacia la comercial del evento; confirmar si también debe ir a otra persona.
3. **Jornada:** confirmar los límites 6, 9 y 12 horas.
4. Decisiones de seguridad abiertas: ver `docs/seguridad/F5-9_*.md` (resumen en `docs/seguridad/F5-9_RESUMEN.md`).
