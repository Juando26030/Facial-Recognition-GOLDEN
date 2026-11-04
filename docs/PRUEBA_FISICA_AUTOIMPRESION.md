# Prueba física de la autoimpresión (Brother QL-800) — guion para Juan David

**Qué se prueba:** que con *autoimpresión* y *autorregistro* encendidos, cada cédula que pasa el lector registra a la persona e imprime UNA sola escarapela, y que los botones Editar e Imprimir de cada fila siguen funcionando.
**Dónde:** staging (nunca producción), con datos ficticios. Chrome normal con su cuadro de impresión; página 62 × 99,8 mm (`docs/IMPRESION_PARAMETROS_INAMOVIBLES.md`). Nunca `--kiosk-printing`.

| # | Haz esto | Debe pasar |
|---|---|---|
| 1 | Abre Registro con **ambos modos apagados**. Después **enciende** autorregistro y autoimpresión (sin recargar). | El aviso de modo cambia solo. |
| 2 | Pasa por el lector la cédula de una persona ficticia **no registrada**. | Queda «Registrado», sale **1** escarapela, aparece de primero con «Recién registrado». |
| 3 | Pasa **la misma** cédula otra vez. | No imprime otra (avisa que ya está). |
| 4 | Escribe otra cédula y pulsa **Enter**; luego otra con **clic** en el resultado. | Cada una: 1 registro y 1 escarapela. |
| 5 | En una fila pulsa **Editar**, cambia un dato y guarda; en otra pulsa **🖨️ Imprimir**. | Ambos botones están y funcionan; Imprimir saca la escarapela a demanda. |
| 6 | Apaga **autoimpresión** (deja autorregistro) y pasa una cédula nueva. | Registra y **no** imprime. |

Mide al final: tamaño y márgenes de la etiqueta iguales a las de siempre. Si algo falla, anota el número de paso y una foto de la pantalla (sin datos reales).
