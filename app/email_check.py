"""Verificación de que un correo "existe" (2026-09-23): formato válido Y que el dominio tenga dónde recibir
correo (registro MX; si no hay MX, el A/AAAA como manda el estándar). NO confirma que el buzón concreto exista
(eso solo se sabe enviando un correo, o preguntándole al servidor por SMTP, que casi nadie responde con
verdad ni deja hacer desde un servidor en la nube) — sí atrapa lo típico: dominios inventados o mal escritos
("gmial.com", "empresa.con")."""
import re
import time
from typing import Tuple

import dns.exception
import dns.resolver

_EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+\.[^@\s]{2,})$")
_CACHE_SECONDS = 3600
_domain_cache: dict = {}  # dominio -> (resultado, hasta_cuándo)


def _domain_receives_mail(domain: str):
    """True/False si se pudo determinar; None si el DNS no respondió (no se puede afirmar nada)."""
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 4.0
    try:
        resolver.resolve(domain, "MX")
        return True
    except dns.resolver.NoAnswer:
        pass  # sin MX: el estándar permite recibir en el A/AAAA del dominio
    except dns.resolver.NXDOMAIN:
        return False
    except (dns.exception.Timeout, dns.resolver.NoNameservers, dns.resolver.YXDOMAIN, dns.exception.DNSException):
        return None
    for rtype in ("A", "AAAA"):
        try:
            resolver.resolve(domain, rtype)
            return True
        except dns.resolver.NoAnswer:
            continue
        except dns.resolver.NXDOMAIN:
            return False
        except dns.exception.DNSException:
            return None
    return False


def check_email(email: str) -> Tuple[bool, str]:
    """(válido, motivo). Ante una falla del propio DNS (sin internet, resolvedor caído) NO se rechaza —
    mejor dejar pasar un correo que bloquear un registro por un problema que no es del usuario."""
    value = (email or "").strip()
    match = _EMAIL_RE.match(value)
    if not match:
        return False, "no tiene el formato de un correo (nombre@dominio.com)"
    domain = match.group(1).lower()
    cached = _domain_cache.get(domain)
    if cached and cached[1] > time.time():
        ok = cached[0]
    else:
        ok = _domain_receives_mail(domain)
        if ok is not None:
            _domain_cache[domain] = (ok, time.time() + _CACHE_SECONDS)
    if ok is False:
        return False, f"el dominio «{domain}» no existe o no recibe correo — revisa cómo está escrito"
    return True, ""
