# Plan de prueba completa de la aplicación (Fases 0 a 9) · 9-nov-2026

Objetivo (pedido de Juan David, 9-nov 18:06): probar **una por una todas las pantallas, todos los flujos y todos los
usuarios** de `f5/integracion`, con archivos e imágenes; arreglar lo que falle; y en paralelo una ronda de seguridad
**contra la aplicación corriendo** (agentes que atacan + agentes que arreglan).

## Por qué no se pudo hacer en la sesión del 9-nov
El contenedor de trabajo ya tiene **PostgreSQL 16** (`/usr/lib/postgresql/16/bin`, probado: arranca y responde),
Chromium + Playwright, Node, `gcc` y `cargo`. Lo único que falta son las librerías de Python de `requirements.txt`
(SQLAlchemy, FastAPI, psycopg2, httpx, bcrypt, qrcode, google-*, dlib/face_recognition…), y la cuenta tenía
**apagada la instalación de paquetes** en la red del entorno. Con eso encendido (ajuste de red de la cuenta, toma
efecto en una conversación nueva) todo este plan corre aquí mismo, **sin Cloud Shell y sin tocar la nube**.

## 1 · Montar el entorno (en el contenedor)
```bash
git clone / fetch  →  rama f5/integracion
pip install --break-system-packages -r requirements.txt      # dlib compila ~10-20 min; si falla, seguir sin él y marcar lo facial
pip install --break-system-packages pytest httpx              # + jsdom con npm para las 14 pruebas JS que lo necesitan
mkdir /tmp/pg && chown postgres /tmp/pg
su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /tmp/pg -A trust -U postgres"
su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /tmp/pg -o '-p 5432 -k /tmp' -l /tmp/pg.log start"
createdb -h /tmp -U postgres golden_e2e ; createdb -h /tmp -U postgres golden_test
# .env de prueba: DATABASE_URL=postgresql://postgres@/golden_e2e?host=/tmp, STORAGE_BACKEND=local,
# JOBS_BACKEND=db, BULK_BACKEND=thread, llaves de cifrado GENERADAS en el momento (nunca las de producción),
# correo en modo «no enviar» (capturar en la tabla/registro), Wompi en sandbox simulado.
alembic upgrade head            # de 0001 a 0121: valida la cadena completa sobre Postgres real
python -m pytest -q             # suite completa (base golden_test)
uvicorn app.main:app --port 5000   # y además APP_MODE=publico / web / biometria en 5001-5003
```

## 2 · Usuarios a probar (una cuenta por rol)
sin sesión (internet) · cliente · digitador · coordinador · comercial · coordinador+comercial · admin · super_admin ·
almacén · contabilidad · almacén+contabilidad · nodo de servidor local (token `X-Node-Token`).
Para cada uno: qué ve en el menú, qué pantallas abren (200) y cuáles deben negarse (403/404/redirige), y que las API
respondan igual que la pantalla (no basta con ocultar el botón).

## 3 · Pantallas (todas las de `templates/`), en computador 1440, ventana angosta 1024/900, tableta y celular, claro y oscuro
Por pantalla: carga sin errores de consola ni respuestas 4xx/5xx inesperadas, esqueleto mientras carga, botón con
rueda al pulsar, imágenes y archivos estáticos responden 200, textos en español sin jerga técnica.

## 4 · Flujos de punta a punta
1. Ingreso, aprobación de inicio de sesión, cambio de contraseña, cierre por inactividad.
2. Plantilla del evento → asistente «Nuevo evento» → editar (incl. `?editar=`) → historial por campo y correos de campos clave.
3. Estados: creado → en proceso (cuadre de inventario y reserva 1/7 días) → finalizado → facturado (base final) ; reglas por rol.
4. Persona `PRUEBA`: única que se registra/imprime en «creado»; nunca en reportes, estadísticas, ruleta ni contadores.
5. Carga masiva (Excel) con progreso, errores por fila; carga de fotos.
6. Registro por cédula y QR; directorio; reimpresión; impresión (solo verificar que NO cambian los parámetros inamovibles).
7. Consentimiento de la auditora → enrolamiento por tarea → reconocimiento (umbral, DUDOSO) → menores sin biometría →
   supresión/revocación (`purge-data`) → purga a 7 días. Con fotos de prueba sintéticas o las de prueba de Juan David, nunca al repo.
8. Formularios públicos: cupo atómico, código de acceso, pago Wompi (sandbox simulado, multicuenta, webhook por cuenta,
   **C1: rechazar transacción de otro comercio**), reembolsos, estadísticas del formulario, URL limpia `/inscripciones/...`.
9. Ruleta, certificados, documentos, legalizaciones, áreas, inventario por evento y catálogo.
10. Turnos y filas + TV; autoregistro en kiosco (**B-01: cédula ajena**); expositores y contactos (QR/NFC); credencial digital y Wallet.
11. Entrega al cliente: enlace, encuesta, descarga de base final, **correo «próximo evento» a la comercial**.
12. Gastos de infraestructura e importación de costos (simulada), cuentas de cobro con llaves cifradas.
13. Alertas de borrado masivo (no silenciables por admin, E-1), copias (simular la semanal a SharePoint sin red real).
14. Servidor local: bajar evento, arrendamiento (nube en solo lectura 423), subida, **«Pasar a internet» bloqueado con datos locales**, cuentas, actualización.
15. Exportar/importar evento completo (solo super_admin) entre dos bases.
16. Estadísticas, enlaces públicos de estadísticas y TV, `/health`, `/ready`, `/sistema`, `/internal/*` solo con token OIDC.

## 5 · Seguridad contra la aplicación corriendo (agentes en paralelo)
Atacantes (sin ver los arreglos): IDOR entre clientes y eventos por rol; escalada de rol; CSRF por Origin; sesión y
cookie `__session`; enlaces públicos y tokens (adivinables, reutilizables, caducidad); subidas (tipos, tamaño, rutas);
inyección en búsquedas/Excel/CSV; webhooks Wompi falsificados; token de nodo fuera de su evento; límites de tasa;
datos personales en logs y respuestas. Defensores: arreglan con prueba que reproduce el ataque y vuelven a correr la suite.

## 6 · Entrega
Informe por flujo y por rol (pasa / arreglado / decisión de Juan David), capturas, commits en `f5/integracion`.
Nada a `main`, nada desplegado, ninguna migración en producción sin autorización expresa.
