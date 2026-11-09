# Fase 6 · Operación sin red — decisiones y plan (9-nov-2026)

Alcance del plan maestro (docs/29 §11): servidor local con sincronización (docs/17); B8 R2–R5 (foto y consentimiento sin red, edición sin red, PIN opcional, dos dispositivos); pruebas en dispositivos reales.
**Listo cuando:** un evento completo se atiende sin internet y al conectarse queda igual en la nube.

## Respuestas de Juan David a las preguntas abiertas de docs/17 (9-nov-2026)
1. **Laptops servidoras:** procesador Intel i5, 8 GB de RAM, Windows 10 u 11 (en promedio).
2. **Reconocimiento facial:** en eventos locales **NO** se maneja si es complicado. → El servidor local corre el servicio «web» (sin `face_recognition`/dlib), solo cédula, QR y búsqueda. Esto además baja el consumo de memoria.
3. **Duración:** un día no pasa de **12 horas**; puede haber varios días de ~12 h cada uno. → Hay noches entre días: el servidor se apaga y se enciende; los datos están en un volumen persistente y se sincroniza apenas haya internet (p. ej. en el hotel).
4. **Quién prepara el servidor:** cualquier cuenta de la empresa (admin, coordinador, comercial, bodega/almacén…) **excepto** los digitadores temporales (tampoco clientes). → El paso de preparación debe ser de un clic y a prueba de errores.

## Decisiones derivadas
- **Opción A (Docker) en modo «web» + PostgreSQL.** Con 8 GB, Docker Desktop (~2–4 GB) + Postgres (1 GB) + app (2 GB) cabe si no hay facial. Plan B (nativo en Windows) solo si Docker falla en las laptops reales.
- **La imagen no se compila en la laptop** (dlib tarda mucho y necesita internet): se construye en la nube y viaja como archivo (`docker save`/`docker load`) o ya viene precargada. Hay que preparar la laptop ANTES de salir (con internet).
- **Permiso de preparación:** `coordinador`, `comercial`, `admin`, `super_admin`, `almacen`, `contabilidad` (rol principal o sumado). Hoy exportar/importar eventos es solo Super Admin (docs/18): para el servidor local se abre a estos roles **sobre eventos a los que pertenecen** (no a todo el sistema).
- **Un solo escritor por evento** (arrendamiento): mientras el evento está en un servidor local, la nube lo marca y lo muestra en solo lectura.
- **Subida reusando lo que ya es idempotente:** el servidor local reenvía sus registros a la nube con los endpoints que ya existen (`access-logs/sync`, `outbox/sync`, identificador único por registro), con un token por nodo revocable. Reenviar nunca duplica.
- B8 R2–R5 (bandeja de salida en cada navegador) siguen siendo la red de seguridad de cada equipo; R4 (PIN y protección del dispositivo) va antes que R2 (foto y consentimiento).

## Etapas (en orden) y estado
| Etapa | Qué | Estado |
|---|---|---|
| **E0 · Kit del servidor** | `deploy/local/` (compose «web»+Postgres, `.env.local.example`), guía de preparación y HTTPS local (docs/17 §2) | Borrador escrito (sin probar: falta Docker y una laptop real) |
| **E1 · Paquete y permiso** | Abrir exportar/importar evento a los roles de arriba (solo sus eventos); el servidor local importa el paquete sin biometría | Por programar |
| **E2 · Arrendamiento + subida** | Marca «en servidor local» en la nube; token por nodo; reenvío por lotes con confirmación; panel de estado (último paquete, última subida, pendientes) | Por programar |
| **E3 · R4 y R2** | PIN opcional / exportación de emergencia; foto y consentimiento sin red | Por programar |
| **E4 · R3 y R5** | Edición sin red con conflictos; dos dispositivos | Por programar |
| **E5 · Dispositivos reales** | Ensayo con laptop i5/8 GB, router y 3–4 equipos; corte de energía y de red; evento simulado de ~12 h | Necesita hardware y a Juan David |

## Lo que NO puedo verificar yo
Nada de esta fase se prueba sin una laptop real con Docker y un router: el kit es un borrador razonado, no probado. Lo programable (permisos, arrendamiento, subida) lleva pruebas automáticas; lo físico lo hacemos juntos en E5.
