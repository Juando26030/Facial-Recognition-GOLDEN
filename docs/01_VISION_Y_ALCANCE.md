# Visión y Alcance — GoldenWeb 2.0

## 1. Visión

Reemplazar el sistema actual de registro y acreditación de eventos de
**Golden Eventos y Logística** por una plataforma propia, modular y
multi-tenant, que iguale o supere la velocidad del flujo actual (cédula por
lector de código de barras) y permita agregar módulos nuevos (biometría,
formularios, pagos, portal de cliente, control de aforo, hardware físico)
sin rediseñar el sistema cada vez.

## 2. Problema que resuelve

- El sistema actual funciona pero no está documentado, tiene deudas técnicas
  conocidas (ver hallazgos de seguridad ya resueltos) y no es fácil de
  extender con nuevos módulos.
- Hay una lista de mejoras pedidas directamente por el equipo que usa el
  sistema día a día (comercial, coordinadores, digitadores) y por quien lo
  opera técnicamente — ver `REQUERIMIENTOS_ROADMAP.md`.
- El negocio necesita poder ofrecer más servicios sobre la misma base
  (biometría, formularios propios, portal de cliente) sin depender de
  integraciones externas rígidas (ej. PayU).

## 3. Objetivos de negocio

1. No perder el diferenciador actual: velocidad del registro en el punto de
   acceso.
2. Dar de baja la dependencia de un sistema legado no documentado y con
   deuda técnica.
3. Habilitar nuevas líneas de servicio (biometría facial ya en curso; huella,
   control de aforo, hardware físico a futuro) sin reescribir el núcleo cada
   vez — de ahí la decisión de arquitectura modular/monorepo.
4. Dar visibilidad a la operación interna (facturación, personal asignado,
   pagos a colaboradores) que hoy se lleva fuera del sistema.
5. Dar autonomía al cliente final (portal con sus propias estadísticas y
   encuestas) en vez de que todo pase por Golden.

## 4. Alcance

### Dentro de alcance (backlog activo — ver `REQUERIMIENTOS_ROADMAP.md`)

- Núcleo de registro/acreditación (cédula, facial, búsqueda, alta manual).
- Kiosko / modo touch.
- Escarapelas (diseño de plantilla e impresión).
- Gestión de eventos, tenants, roles y ciclo de vida (**ya construido**).
- Formularios web propios.
- Informes y reportes por evento.
- Portal de cliente.
- Gestión de personal y facturación interna.
- Actas de novedades digitales.

### Fuera de alcance por ahora (Won't, hasta resolver una duda o decisión)

- Módulo de huella dactilar — pendiente validar legalidad (Ley 1581 de
  protección de datos personales en Colombia, tratamiento de datos
  biométricos sensibles).
- Ruleta / gamificación — valor de negocio no confirmado.
- Integración con el sistema "rompefila" de Jose — no está claro todavía si
  es un proveedor externo o un módulo a construir.
- Sync offline/online completo — de alta complejidad (XL); se evalúa después
  de tener el núcleo en producción.

## 5. Stakeholders y roles del negocio

| Rol de negocio | Quién | Rol en el sistema (ya construido) |
|---|---|---|
| Comercial | Crea el evento, lo asocia a un cliente | `admin` / `coordinador` según el caso |
| Coordinador | Activa el evento, gestiona el punto de registro | `coordinador` |
| Digitador | Opera el registro el día del evento | `digitador` (temporal, atado a un evento) |
| Cliente final | Empresa que contrata a Golden para su evento | `cliente` (solo su evento, estadísticas y directorio) |
| Operación interna (Gloria, personal) | Factura, paga colaboradores | Sin rol propio todavía — parte del backlog (M4) |

## 6. Criterios de éxito

- GoldenWeb 2.0 puede operar un evento real de principio a fin (carga de
  base, registro por cédula o facial, escarapela, informe final) sin
  depender del sistema viejo.
- El tiempo de registro por persona no empeora frente al sistema actual.
- Un módulo nuevo (ej. control de aforo) se puede agregar sin tocar el
  núcleo de registro — validación directa de la meta de arquitectura modular.

## 7. Supuestos y restricciones

- Un solo desarrollador construye el sistema con apoyo de un agente de
  código (Claude Code); la documentación tiene que compensar la falta de
  equipo grande, no un proceso Scrum de varias personas.
- Infraestructura ya definida: VM en GCP, PostgreSQL, Nginx/Cloudflare,
  despliegue automático por GitHub Actions (self-hosted runner).
- El repositorio del núcleo facial (`Facial-Recognition-GOLDEN`) migra a
  monorepo (`apps/<módulo>/`) para alojar los módulos nuevos — decisión ya
  tomada, ejecución pendiente.
