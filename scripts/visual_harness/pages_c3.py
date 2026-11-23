"""Pantallas del CRM C3 (cotizaciones, productos, búsqueda) para el arnés visual (datos ficticios en mocks_c3.py)."""
_PAGES = {'crm_cotizaciones': ('crm_cotizaciones.html', {}), 'crm_cotizacion': ('crm_cotizacion.html', {'quote_id': 1}), 'crm_productos': ('crm_productos.html', {}), 'crm_buscar': ('crm_buscar.html', {})}


def context(key, v, Obj, simple):
    if key not in _PAGES:
        return None
    tpl, extra = _PAGES[key]
    return tpl, {**simple, 'staff_role': 'admin', 'sidebar_active': 'crm', 'can_admin': True, **extra}
