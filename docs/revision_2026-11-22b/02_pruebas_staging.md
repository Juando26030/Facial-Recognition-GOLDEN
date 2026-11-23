# Fase 3 — Pruebas en staging con sesión (23-nov-2026, commit `b0cc145` y posteriores)

Hecho por Claude en el navegador integrado con la sesión de Juan David (super_admin) y, para el aislamiento, con la cuenta ficticia `prueba_admin`. Lista base: `docs/PRUEBAS_STAGING_2026-11-23.md`.

| # | Prueba | Resultado |
|---|---|---|
| 1 | Empresas (SaaS): crear «PRUEBA Empresa Ficticia» y su administrador | ✔ La contraseña se muestra una vez. **Falló el botón «Copiar»** (el navegador integrado negó el portapapeles): arreglado, usa el copiador común (`7e99c59`); falta verlo en staging. |
| 2 | Límite del plan | ✔ Primer evento creado; el segundo → 403 «Tu plan permite 1 evento por mes; contacta a soporte». |
| 3 | «¿Qué sigue?» al crear evento | No probado (requiere el flujo de pantalla). |
| 4 | Confirmaciones que piden escribir la palabra | No probado. |
| 5 | Formulario con pago «Activo» | No probado. |
| 6-8 | Digitador (menú, Editar, tabla de Registro) | No probado: no hay sesión de digitador (las contraseñas las escribe Juan David). |
| 9-13 | **Foto pendiente (C)** | No probado: necesita una selfie con una cara real. Código revisado: `app/routers/aceptar.py` guarda la selfie en `*.pending.jpg` si la persona ya tiene foto, no está verificada y el interruptor está activo. Pasos para Juan David al final del reporte. |
| 14-17 | Servidor local (D) | No probado (portátil de prueba). |
| 18 | Sitio: teléfono y correo oficiales, Poppins | ✔ (portada; 320-1440 px sin desplazamiento horizontal de la página; en 768 px un paso quedaba cortado → arreglo en la rama `fix/pasos-tablet` del sitio, sin compilar aún). |
| 19 | Sitio de staging no indexable | ✔ `noindex` y `Disallow: /` (script corregido, `4dee01f`). |
| 20 | Cotización | ✔ «Recibimos su solicitud…» tras crear el secreto de staging. **Hallazgo:** sin el secreto responde 503 también en staging; el nombre real es `golden-quote-to-email[-staging]` y hace falta darle permiso de lectura a `golden-app` y `golden-ops` (README corregido). |
| 21 | Salud: `/health` y semáforos | `/health` 200. En «Estado del sistema»: rojo = último respaldo hace 178 h (staging apagado, no es de esta rama); amarillos = 1 trabajo fallido (los correos de cotización no salen en staging, esperado), copia semanal sin configurar, 3 eventos en curso, 1 evento terminado sin finalizar (bloquea el borrado a los 7 días). Nada nuevo atribuible a la rama. |
| 22 | Pruebas con navegador (E2E) | No corridas. |

## Pasos para Juan David: foto pendiente (C), 10 minutos, con tu propia cara
1. Parámetros del evento de prueba › busca «Verificar antes de reemplazar la foto»: debe estar **activo**.
2. Elige una persona de prueba que YA tenga foto de registro. Abre `/aceptar` sin su enlace personal, escribe su cédula y fecha y tómate una selfie. *Debe:* la foto que ve el operador **no cambia**.
3. Verifica a esa persona (enlace personal o personal del evento). *Debe:* ahora sí cambia la foto.
4. Apaga el interruptor y repite el paso 2. *Debe:* la selfie reemplaza la foto de una vez.
5. Suprime los datos de esa persona. *Debe:* no queda ninguna de las dos fotos.
