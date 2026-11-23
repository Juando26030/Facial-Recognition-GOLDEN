# Coordinador temporal del evento (16-nov-2026)

Pedido de Juan David: una persona con los permisos de un coordinador pero SOLO sobre el evento que se le asigna: no ve otros eventos, ni la lista de clientes, ni el CRM, ni configuraciones, ni el calendario de los demás.

## Qué es
- Cuenta `staff_users` con `role = coordinador` y `event_only = true` (migración `0146_event_only_staff`). Se asigna a uno o varios eventos con `EventStaffAuthorization`, igual que un digitador temporal.
- Se crea en **Usuarios del evento → Nueva cuenta → Rol «Coordinador temporal (solo este evento)»**. Solo la crea una **comercial, un admin o el super admin** (un coordinador, ni siquiera temporal, no crea coordinadores).
- **Se crea igual que un coordinador normal** (cambio del 16-nov-2026, 21:25): quien lo crea (comercial, admin o super admin) escribe usuario, contraseña inicial (política estricta), nombre y teléfono (obligatorio y único); el correo es opcional y, si lo hay, sale el aviso de siempre (sin contraseña). La persona elige su contraseña en el primer ingreso. La ÚNICA diferencia con un coordinador normal es el alcance: solo el evento asignado.
- Queda en `audit_actions` (`entity = event_only_coordinator`; ids, nunca el usuario).

## Qué puede hacer
Todo lo que un coordinador hace DENTRO de su evento: registrar, directorio, escarapelas, parámetros, formularios, ruleta, estadísticas, crear/administrar digitadores temporales de su evento, pasar el estado del evento.
Su lista de eventos y su calendario solo muestran sus eventos (`auth.scope_events_query`). Al entrar va derecho a su evento si es uno solo.

## Qué NO puede (y dónde se hace cumplir)
1. **`app/event_only.py`** (lista de PERMITIDOS; lo que no está, se cierra): la usa el middleware `event_only_gate` de `app/main.py` con la sesión (`staff_event_only`) y otra vez `auth.get_current_staff` con la base. Páginas cerradas: `/clientes`, `/crm`, `/configuracion`, `/inventario`, `/gastos`, `/cuentas-de-cobro`, `/sincronizacion`, `/servidor-local`, `/impresion-usb`, `/sistema`, `/admin`, `/eventos/nuevo`. API: solo las de operar en un evento; cerradas CRM, clientes, staff, gastos, inventario, importar/exportar, crear o duplicar eventos, notas del calendario…
2. **Pertenencia**: `auth._scope_applies` vale SIEMPRE para esta cuenta (aunque `ENFORCE_STAFF_EVENT_SCOPE` esté apagado) y solo cuenta su autorización explícita; `/api/events/{id}/…` y `/kiosk/{id}/…` con un evento ajeno responden 404.
3. **Fin del acceso**: cuando el evento pasa a «finalizado» (o se archiva) deja de entrar (`get_event_for_staff` → 403; no sale en listas).
4. No aparece en la lista de cuentas de Staff ni como «coordinador asignado» de un evento (`/api/staff` y `/api/staff/coordinators` la excluyen): se administra desde «Usuarios del evento».

## Decisiones tomadas (revisables)
- Crearla: comercial o más. Quitarla/eliminarla: lo mismo (el coordinador no).
- Sin correo ni restablecer contraseña (la contraseña no se vuelve a ver): se elimina y se crea otra.
- Acceso mientras el evento esté «creado» o «en proceso»; al finalizar termina solo.
- «Eliminar los usuarios temporales» NO la toca (solo digitadores): se elimina una por una.

## Pruebas
`tests/test_coordinador_temporal.py` (reglas puras + de punta a punta) y la comprobación de que ninguna ruta de las familias globales queda abierta, existan hoy o se agreguen después.

## Ciclo de vida de la cuenta (16-nov-2026, 2.ª parte)
- **Digitadores:** el coordinador temporal crea digitadores temporales en SU evento y autoriza sus ingresos (`login-state`, `login-request`, `approve-all`, `unlock`); en otro evento recibe 404.
- **Al terminar el evento la cuenta NO se borra ni se desactiva:** solo pierde el acceso a ese evento (queda sin eventos). El borrado sigue siendo manual (comercial+).
- **Reasignar:** un comercial/admin la busca en «Asignar cuentas ya existentes» (`GET /api/staff/assignable`, el comercial solo ve coordinadores temporales; `POST .../staff-users/assign-existing`) y recupera el acceso solo al evento nuevo. Nunca se avisa por correo; el digitador existente sigue siendo solo de admin+.
- El coordinador temporal NO puede asignar cuentas (`assign-existing` y `/api/staff/assignable` están cerradas para él).
- Pruebas: `tests/test_coordinador_temporal.py` (requieren la base `golden_test`; en esta sesión sin psycopg2 solo se verificó sintaxis, ruff y plantilla).
