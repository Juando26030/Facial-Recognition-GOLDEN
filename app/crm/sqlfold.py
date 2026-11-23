"""Búsqueda de texto libre sin tildes ni mayúsculas en columnas que no tienen columna `_norm`, sin migración.
`fold(col)` se compara contra un texto ya pasado por `app.crm.normalize()`. Las letras acentuadas se traducen en ambas formas (minúscula y mayúscula) ANTES de pasar a minúsculas,
para no depender de la configuración regional de la base. La tabla es UNA lista de pares: `_FROM` y `_TO` se derivan de ella y no pueden desalinearse."""

_LOWER_PAIRS = (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n"), ("à", "a"), ("è", "e"), ("ì", "i"), ("ò", "o"), ("ù", "u"),
                ("â", "a"), ("ê", "e"), ("î", "i"), ("ô", "o"), ("û", "u"), ("ä", "a"), ("ë", "e"), ("ï", "i"), ("ö", "o"), ("ç", "c"))
PAIRS = _LOWER_PAIRS + tuple((a.upper(), b.upper()) for a, b in _LOWER_PAIRS)
_FROM = "".join(a for a, _ in PAIRS)
_TO = "".join(b for _, b in PAIRS)


def fold(column):
    from sqlalchemy import func                      # import tardío: la tabla de arriba se puede probar sin SQLAlchemy
    return func.lower(func.translate(column, _FROM, _TO))
