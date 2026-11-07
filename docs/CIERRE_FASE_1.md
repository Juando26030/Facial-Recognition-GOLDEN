# Cierre oficial de la Fase 1 — 7-nov-2026

Cierre ordenado por Juan David (7-nov-2026, 02:24 Bogotá). Fase 1 = rediseño visual de las pantallas internas (1.5 a 1.14), cupos y formularios, y el cierre de seguridad. La Fase 2 empieza ahora.
Producción corre `1951bea93bb5d04cfb04afca6fcd8903c667e33c` (`main`), desplegada el 7-nov a las 02:16 (hora de Bogotá).

## Qué se hizo
**Rediseño visual (Fase 1.5 a 1.14).** Todas las pantallas internas pasaron al sistema de diseño nuevo (tokens `--gw-*`, claro y oscuro): Registro del digitador con buscador grande, Inicio y «Elegir qué hacer» con mosaicos, Eventos, Clientes, Calendario, Usuarios, Formularios, Estadísticas (con gráficos legibles en celular), Áreas, Inventario, Documentos, Legalizaciones, Certificados, Ruleta (rueda y proyector rediseñados), Parámetros, Estado del sistema, editor de formularios y diseñador del formulario de persona. Escritorio con filas delgadas y ancho completo; celular con tarjetas, objetivos táctiles de 44 px y un solo «Escanear». Páginas públicas **congeladas** (decisión del 5-nov).
**Cupos y formularios.** Cupos con calendario propio y fecha de cierre; lista de personas ya registradas que resta de los cupos; unificar valores (Bogota/BOGOTÁ → Bogotá); alinear inscripciones a la ciudad de la base sin pasarse del cupo; negrilla en el mensaje de cupo lleno; formulario público sin asteriscos y con «(opcional)».
**Cierre de seguridad.** Permisos, IDOR y aislamiento por cliente (P); cierre del formulario público X1–X7 (escarapela y datos de quien ya existe, cédula verificada, pre-llenado enmascarado, pagos pendientes por IP); topes reales en Excel e imágenes verificadas (ángulo I); ingreso de digitadores con aprobación del coordinador, bloqueo a los 3 intentos, sesiones que sí se invalidan, IPv6 por /64, `SECRET_KEY` validada, `/ready` sin detalles (S1–S11; ver `SEGURIDAD_SESIONES.md`, migración `0086_digitador_login_control`).
**Regla de Juan David sobre X1:** la escarapela de quien ya existe va primero al contacto ya registrado y, si no hay, al correo del formulario; nunca se sobrescribe un contacto existente.
**Orden del repositorio:** 84 ramas borradas (de 155 a 71 en GitHub), lista y SHA en `0D_ramas_borradas_cierre_fase1.txt`; se conservaron las de trabajo único. Recuperar una: `git push origin <sha>:refs/heads/<nombre>`.

## Pruebas
Suite completa con base real (Cloud Shell, `scripts/pruebas_cloudshell.sh`): **2242 pasaron, 9 se saltan, 0 fallan**; pruebas de JS en verde; ruff limpio. Se corrigió 1 falla real (X1) y 1 sondeo que ignoraba la pausa por inactividad; el resto eran pruebas viejas.

## Despliegues
| Fecha | Commit | Nota |
|---|---|---|
| 6-nov noche | `0f98f15` | cierre de seguridad completo, sin evento en curso |
| 7-nov 02:16 | `1951bea` | regla X1 y sondeo de Usuarios; sin migraciones nuevas |
Sistema en verde tras cada despliegue. Copias de Neon antes: `antes-produccion-6nov`, `antes-produccion-7nov` (sin borrado automático). Revisiones previas para volver atrás: `golden-web-00026-7pb`, `golden-publico-00026-k77`, `golden-biometria-00026-nvw`.

## Formulario de Fundación Social (formulario 4, evento 11)
Se comparó antes y después del despliegue. Diseño, ajustes, horario, campos del evento y personas en base (9739) **no cambiaron**. Las diferencias frente a la foto del 6-nov (estado abierto sin calendario, 5687 inscripciones confirmadas en vez de 5698, cupos usados) ya estaban en la copia de las 02:12, antes del despliegue: Juan David confirmó que fueron cambios pedidos por el cliente y hechos por él. El código del despliegue no tocó datos.

## Decisiones y pendientes que pasan a la Fase 2 o a su dueño
- Apellido obligatorio o no en «Registrar nuevo» (decide Juan David).
- CSP con `script-src`: probar primero en modo «solo reportar» (Fase 3, ya estaba anotado).
- Cortafuegos de la VM antigua (S4, `SEGURIDAD_SESIONES.md`): lo hace Juan David, o se cierra con la VM.
- `ENFORCE_STAFF_TENANT=1` con dos clientes antes de ofrecer el SaaS.
- GitHub Actions sigue bloqueado por facturación (Settings → Billing); mientras tanto, pruebas con el script de Cloud Shell.
- Staging pausado (programador y mínimos en cero): reactivarlo antes de probar o desplegar ahí.
- Correo de restablecimiento dentro de la petición (S6, bajo).
- Escáneres (gitleaks, pip-audit, Bandit, Semgrep) siguen informativos.

## Pendiente visual que hereda la Fase 2
Ver `ux/PENDIENTES_VISUALES.md` (editor de opciones, ventanas de Registro, `toast.js`, hoja vieja `style.css`, pestaña «Escáner de acceso») y el buscador «¿qué quieres hacer?», que NO está construido.
