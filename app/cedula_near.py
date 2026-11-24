"""Cédula leída a medias (reflejo, poca luz) → cédulas PARECIDAS de la base (24-nov-2026, pedido de Juan David).

Regla de oro: esto NUNCA acredita a nadie. Solo arma la lista «No se leyó completa: ¿es alguna de estas personas?» y el operador elige; la persona
elegida entra por el camino exacto de siempre (`checkin-cedula`). «Está» / «No está» siguen saliendo solo de una lectura VALIDADA (dígitos de
control de la cédula nueva, corrección de errores del código de barras de la vieja) con coincidencia exacta.

Parecida = a UN error de lectura de distancia: un dígito cambiado, uno de más, uno de menos o dos vecinos intercambiados (lo típico de un brillo
sobre un número). Con eso se generan todas las variantes (≈200 para 10 dígitos) y se buscan por igualdad (usa el índice), sin recorrer personas.
Sin acceso a base: se prueba en Node/pytest sin Postgres."""
import re

MIN_DIGITS = 5          # con menos dígitos casi cualquier cédula sería «parecida»: no se ofrece nada
MAX_DIGITS = 12
DIGITS = "0123456789"


def clean(value) -> str:
    """Solo los dígitos de lo leído (la cédula nueva puede traer «<» de relleno o letras confundidas)."""
    return re.sub(r"\D", "", str(value or ""))[:MAX_DIGITS]


def variants(read: str) -> list:
    """Todas las cédulas a un error de lectura de `read` (sin incluir `read`). Orden estable: primero las del mismo largo (lo más común)."""
    d = clean(read)
    if len(d) < MIN_DIGITS:
        return []
    out, seen = [], {d}

    def add(v):
        if v and v[0] != "0" and MIN_DIGITS <= len(v) <= MAX_DIGITS and v not in seen:          # una cédula colombiana no empieza por 0
            seen.add(v)
            out.append(v)
    for i in range(len(d)):                                   # un dígito mal leído
        for c in DIGITS:
            add(d[:i] + c + d[i + 1:])
    for i in range(len(d) - 1):                               # dos vecinos intercambiados
        add(d[:i] + d[i + 1] + d[i] + d[i + 2:])
    for i in range(len(d)):                                   # un dígito de más (se leyó un brillo como número)
        add(d[:i] + d[i + 1:])
    for i in range(len(d) + 1):                               # un dígito de menos (el brillo tapó uno)
        for c in DIGITS:
            add(d[:i] + c + d[i:])
    return out
