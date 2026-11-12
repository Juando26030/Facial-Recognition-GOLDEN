"""Búsqueda de texto libre sin tildes ni mayúsculas en columnas que no tienen columna `_norm`, sin migración.
`fold(col)` se compara contra un texto ya pasado por `app.crm.normalize()`. Las letras acentuadas se traducen en ambas formas (minúscula y mayúscula) ANTES de pasar a minúsculas,
para no depender de la configuración regional de la base."""
from sqlalchemy import func

_FROM = "áéíóúüñàèìòùâêîôûäëïöçÁÉÍÓÚÜÑÀÈÌÒÙÂÊÎÔÛÄËÏÖÇ"
_TO = "aeiouunaeiouaeiouaeioucAEIOUUNAEIOUAEIOUAEIOC"
assert len(_FROM) == len(_TO)


def fold(column):
    return func.lower(func.translate(column, _FROM, _TO))
