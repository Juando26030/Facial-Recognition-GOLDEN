# Fase 0C — Cierre (3-nov-2026)

## Resultado
- **Críticos abiertos: 0. Altos abiertos: 0.** Las 7 familias altas de `0C_hallazgos_pasada2.md` están arregladas y en `main` (PR #13, #14, #16, #17), con pruebas (`tests/test_seguridad_0c_altas.py`) y verificadas en staging.
- **Prueba dinámica (OWASP ZAP, solo staging, datos ficticios, respaldo de Neon `respaldo-pre-zap-2026-11-02`, correo y pagos sin credenciales reales):** baseline 0 fallos / 8 avisos; completa (ataque activo) **0 fallos / 7 avisos / 136 comprobaciones superadas**. Sin hallazgos medios, altos ni críticos.
- Escáneres en CI (gitleaks, pip-audit, Bandit, Semgrep): corren en cada PR y cada lunes; siguen **informativos** (`continue-on-error`).

## Avisos de ZAP aceptados (con motivo)
| Aviso | Decisión |
|---|---|
| CSP sin directivas completas | Una política estricta rompería los scripts propios; queda `frame-ancestors`, `object-src`, `base-uri`. Revisar en la Fase 3 (matriz de permisos) |
| Sin tokens anti-CSRF | Defensa vigente: cookie SameSite=Lax + verificación de `Origin` |
| COEP/CORP, marcas de tiempo, cabeceras de caché, «Proxy Disclosure» | Informativos; COEP/CORP romperían recursos externos (cámara, Wompi) |
| `X-Content-Type-Options` en 1 ruta | Ruta estática fuera del middleware; pendiente de ubicar |

## Medios abiertos (con fecha, todos antes de la Fase 1A)
Lote 2 (miércoles 4-nov a viernes 6-nov): C7 bloqueo de login por (usuario, IP) · C8 contador por cédula en `/aceptar` · C11 política de contraseñas al crear personal · C4/C15 amarrar la cédula tecleada a la invitación · C5 pago aprobado sin inscripción · E2/E3 cédulas en `jobs.payload_json` y errores sin enmascarar · E4 directorio con datos personales para rol `cliente` · E8 cuentas de servicio separadas por servicio · A2/A6/A7 `PUT /users` y alcance por pertenencia al evento · B3/B-N1 topes de ZIP e imágenes · D9 `integrity` en librerías de CDN · E-N1 revocación por evento. Bajos: backlog con fecha de 2 semanas.

## Dos lecciones
1. Subir `setuptools` ≥ 82 rompió el arranque (`pkg_resources`); lo detectó staging, no producción. Pin 69.5.1 con comentario. Pendiente: prueba de CI que importe el motor facial.
2. `ENFORCE_STAFF_TENANT` queda en 0 (hoy un solo tenant); encenderlo en staging con datos de dos tenants es requisito antes del SaaS.

## Lote 2, grupo B (rama `fix/0c-lote2-b`, en revisión)
C5 pago aprobado sin inscripción · E2/E3 cola sin cédulas ni errores sin enmascarar (migración `0078_jobs_sin_cedulas`, solo datos) · E4 directorio enmascarado para `cliente` · E8 cuentas por servicio (apagado por defecto, pasos en [`20_CUENTAS_POR_SERVICIO.md`](20_CUENTAS_POR_SERVICIO.md)) · A2 `PATCH /users` con lista blanca · A6/A7 alcance por pertenencia al evento (`ENFORCE_STAFF_EVENT_SCOPE`, apagado por defecto; encenderlo en staging antes del SaaS) · E-N1 revocación por evento. Pruebas: `tests/test_seguridad_0c_lote2_b.py`.

## Para producción
Todo lo anterior está en `main` pero **no desplegado a producción**. Entrega con la receta habitual (copia de Neon, workflow manual, verificación y punto de retorno) solo con la autorización escrita de Juan David.
