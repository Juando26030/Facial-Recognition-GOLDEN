"""Unificar valores de un campo que define cupos (p. ej. «Bogota», «BOGOTÁ» y «Bogotá, D.C.» → «Bogotá»). Lógica pura: sin base ni HTTP.

El valor correcto de cada cupo es el que está escrito en la regla (`Ciudad = Bogotá`). Un valor guardado se corrige solo si, sin tildes ni mayúsculas ni espacios de más, es
IGUAL a un valor de una regla, o si el organizador dio un alias explícito («Bogotá, D.C.» → «Bogotá»). Nada se adivina: lo que no coincide queda como está y se informa."""
from typing import Optional

from app.formlib import norm_value


def canonical_values(rules: list, field_id: str) -> dict:
    """{valor normalizado: valor escrito en la regla} de las condiciones `igual a` / `está en` sobre el campo."""
    out = {}
    for r in rules:
        for c in r.get("conds", []):
            if c.get("field") != field_id or c.get("op") not in ("equals", "in"):
                continue
            wanted = c.get("value")
            for w in (wanted if isinstance(wanted, list) else [wanted]):
                if isinstance(w, str) and w.strip():
                    out.setdefault(norm_value(w), w.strip())
    return out


def alias_map(aliases: dict, canon: dict) -> dict:
    """{alias normalizado: valor canónico}. Un alias cuyo destino no es un valor de las reglas es un error (ValueError): así no se inventan ciudades."""
    out = {}
    for src, dst in (aliases or {}).items():
        target = canon.get(norm_value(dst))
        if target is None:
            raise ValueError(f"«{dst}» no es un valor de los cupos de este campo")
        out[norm_value(src)] = target
    return out


def resolve(value, canon: dict, aliases: dict) -> Optional[str]:
    """Valor corregido, o None si no hay nada que cambiar o no se reconoce (texto vacío, listas, valores sin regla)."""
    if not isinstance(value, str) or not value.strip():
        return None
    key = norm_value(value)
    return canon.get(key) or aliases.get(key)
