"""Pantallas del CRM C2/C1c para el arnés visual (datos ficticios en mocks_c2.py)."""
_PAGES = {'crm_oportunidades': ('crm_oportunidades.html', {}), 'crm_oportunidad': ('crm_oportunidad.html', {'opportunity_id': 1}), 'crm_leads': ('crm_leads.html', {}),
          'crm_embudos': ('crm_embudos.html', {}), 'crm_importar': ('crm_importar.html', {})}


def context(key, v, Obj, simple):
    if key not in _PAGES:
        return None
    tpl, extra = _PAGES[key]
    return tpl, {**simple, 'staff_role': 'admin', 'sidebar_active': 'crm', 'can_admin': True, **extra}
