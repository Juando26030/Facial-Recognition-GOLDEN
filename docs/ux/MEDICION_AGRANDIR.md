# Agrandir en el rediseño: qué se midió (17 oct 2026)

El panel y `/aceptar` usan **Agrandir** (decisión del dueño, Sprint 2.4 Fase 9): `agrandir-thin.ttf` para el texto normal (pesos 100–500) y `agrandir-regular.otf` para 600 o más. El rediseño ya no impone otra fuente: `--ux-font` sigue a `--font-body` y los títulos a `--font-heading-secondary`, así que lo que se elija en Configuración > Apariencia manda.

## Grosor del trazo (del propio archivo de la fuente)
| Peso | Tallo de la «l» | A 16 px |
|---|---|---|
| Thin (hoy el cuerpo) | 0,040 em | **0,64 px** (menos de un píxel: se dibuja como un gris, no como negro) |
| Regular | 0,076 em | 1,22 px |

## Contraste real en pantalla (Chrome, texto real; núcleo del trazo = 0,25 % de píxeles más oscuros)
| Texto | Pantalla | Contraste del color | Thin: núcleo del trazo | Regular: núcleo |
|---|---|---|---|---|
| Cuerpo 16 px, tinta #1b1d2a | normal (1×) | 16,7:1 | **8,8:1** | 16,7:1 |
| Ayuda 14 px, gris #4a4d5c | normal (1×) | 8,4:1 | **5,0:1** | 8,4:1 |
| Cuerpo y ayuda | iPad / celular (2×) | 16,7 y 8,4:1 | igual al nominal | igual |

Conclusión: con Thin los colores cumplen 4,5:1 sobre el papel, pero en un monitor normal el texto de ayuda llega a 5,0:1 en el trazo (apenas por encima del límite; con un gris un poco más claro ya no cumpliría), y se ve visiblemente más pálido que con Regular (ver `capturas/agrandir_ipad_parametros.png`). En pantallas de alta densidad (iPad, celulares) el trazo sí se renderiza completo. Propuesta (no aplicada, decide el dueño): usar Regular (peso 600) solo para texto de ayuda, etiquetas y campos de formulario de 14–16 px; Thin se queda en los textos de 18 px o más.

## Licencia
Los archivos traen: «Copyright © 2018 by Alexander Slobzheninov. All rights reserved.» No traen texto de licencia, ni URL de licencia; el campo de permisos de incrustación (`fsType`) vale 4 («solo vista previa e impresión»), que en la práctica no autoriza servirla como fuente web. En el repositorio no consta ninguna licencia web (`docs/historial.md` solo dice «fuente comercial… provista por Juan David»). Hay que pedirle al proveedor la licencia web y guardarla en `docs/legal/`.

## Decisión del dueño (17 oct 2026): aplicada
Todo texto de menos de 18 px (cuerpo, ayuda, etiquetas y campos de formulario) usa el peso 600 = Agrandir Regular (`--ux-weight-small` en `static/css/ux1.css`); Thin queda para 18 px o más (hoy ningún texto: los títulos ya van en 700). Medido: ayuda 14 px, 8,4:1 también en el trazo; cuerpo 16 px, 16,7:1. Capturas: `capturas/agrandir_*.png`.
Efecto secundario a tener en cuenta: como Thin y Regular ahora se ven iguales de pesados, una negrilla dentro de un párrafo («**Usa rostro.** Quien acepte…») ya no se distingue por peso (700 también cae en Regular); si hace falta énfasis, hay que usar color o tamaño. Y si alguien elige otra tipografía en Configuración > Apariencia, 600 es semi-negrita en esa familia.

## Verificación sobre la página real (Parámetros > Reconocimiento facial, Chrome, 17 oct, tras aplicar el peso 600)
Núcleo del trazo = 0,25 % de píxeles más oscuros del elemento, contra su fondo real.
| Elemento | Peso / tamaño | Monitor normal (1×) | iPad / celular (2×) |
|---|---|---|---|
| Ayuda bajo el título de la tarjeta | 600 / 14 px | **8,4:1** | 8,4:1 |
| Etiqueta («Responsable del tratamiento») | 600 / 16 px | **16,7:1** | 16,7:1 |
| Campo de formulario (select) | 600 / 16 px | **16,7:1** | 16,7:1 |
| «Todo guardado» | 600 / 14 px | **8,4:1** | 8,4:1 |
| Introducción de la pestaña | 600 / 16 px | **7,5:1** (sobre el fondo gris de la página) | 7,5:1 |

Todos cumplen 4,5:1 en el trazo (antes, con Thin, la ayuda llegaba a 5,0:1 en un monitor normal). Comparación visual: `capturas_ronda2/paso1_antes_thin_ipad.png` y `paso1_despues_regular_ipad.png`.
