"""Pantallas del CRM C4 (Mi día, tableros) para el arnés visual (datos ficticios en mocks_c4.py)."""
_PAGES = {'crm_midia': ('crm_midia.html', {}), 'crm_tableros': ('crm_tableros.html', {})}


def context(key, v, Obj, simple):
    if key not in _PAGES:
        return None
    tpl, extra = _PAGES[key]
    return tpl, {**simple, 'staff_role': 'admin', 'sidebar_active': 'crm', 'can_admin': v != 'comercial', **extra}
