"""Cliente temporal del evento (12-nov-2026, pedido de Juan David): cuenta con los MISMOS permisos que un digitador temporal (su rol es `digitador`) para el cliente que también
necesita intervenir en la base del evento, pero que ingresa con un usuario y una contraseña propios y aleatorios, sin la solicitud de ingreso que autoriza el coordinador
(`staff_users.client_temp`, `login_control.applies`).

Reglas:
  * El usuario y la contraseña los genera el servidor (secrets, sin caracteres que se confundan: nada de 0/O ni 1/l/I) y se muestran UNA sola vez al coordinador;
    la contraseña nunca se guarda en claro, nunca va por correo ni a los registros.
  * La contraseña cumple la política estricta (10+ caracteres, letra y número, no común) y no vence: la cuenta es del evento y se borra con «Eliminar los usuarios temporales».
  * El usuario lleva el prefijo `cli-` para distinguirlo de una cédula a simple vista.
"""
import secrets
from typing import Callable

from app import security

USER_PREFIX = "cli-"
USER_LEN = 6
PASSWORD_LEN = 14
_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz"          # sin I, O, l (se confunden con 1 y 0)
_DIGITS = "23456789"                                                   # sin 0 y 1
_SAFE = _LETTERS + _DIGITS


def new_username(exists: Callable[[str], bool], tries: int = 50) -> str:
    """Un usuario `cli-xxxxxx` que no exista todavía (`exists` consulta la base). Minúsculas y cifras: se dicta y se escribe sin errores."""
    alphabet = "abcdefghjkmnpqrstuvwxyz" + _DIGITS
    for _ in range(tries):
        name = USER_PREFIX + "".join(secrets.choice(alphabet) for _ in range(USER_LEN))
        if not exists(name):
            return name
    raise RuntimeError("No se pudo generar un usuario libre")


def new_password(username: str = "") -> str:
    """Contraseña aleatoria que SIEMPRE pasa la política estricta (letra y número, no común, distinta del usuario)."""
    for _ in range(100):
        pw = "".join(secrets.choice(_SAFE) for _ in range(PASSWORD_LEN))
        if any(c.isalpha() for c in pw) and any(c.isdigit() for c in pw) and not security.password_problem(pw, username, strict=True):
            return pw
    raise RuntimeError("No se pudo generar una contraseña válida")
