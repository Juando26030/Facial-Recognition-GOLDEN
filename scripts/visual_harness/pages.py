"""Contextos simulados (TODO ficticio) por pantalla. context(clave, variante, Obj) -> (plantilla, contexto)."""
import datetime
import importlib.util
import json

_CRM_SECTIONS = (('cuentas', 'Cuentas', '/crm', 0), ('oportunidades', 'Oportunidades', '/crm/oportunidades', 0), ('leads', 'Leads', '/crm/leads', 0), ('cotizaciones', 'Cotizaciones', '/crm/cotizaciones', 0),
                 ('midia', 'Mi día', '/crm/mi-dia', 0), ('tableros', 'Tableros', '/crm/tableros', 0), ('buscar', 'Buscar', '/crm/buscar', 0), ('embudos', 'Embudos', '/crm/embudos', 1), ('importar', 'Importar', '/crm/importar', 1))
LONG_EVENT = 'Congreso Nacional de Innovación, Tecnología Aplicada y Transformación Digital 2026'
LONG_TENANT = 'Asociación Colombiana de Ingenieros de Sistemas y Telecomunicaciones'
LONG_STAFF = 'María Fernanda Rodríguez Valderrama'

FIELD_CONFIGS = [
    {'key': 'id', 'label': 'Cédula', 'visible': True, 'required': True, 'type': 'text'},
    {'key': 'first_name', 'label': 'Nombres', 'visible': True, 'required': True, 'type': 'text'},
    {'key': 'last_name', 'label': 'Apellidos', 'visible': True, 'required': True, 'type': 'text'},
    {'key': 'opt_1', 'label': 'Tipo de asistente', 'visible': True, 'required': False, 'type': 'text'},
    {'key': 'entity', 'label': 'Empresa', 'visible': True, 'required': False, 'type': 'text'},
]


def survey():
    spec = importlib.util.spec_from_file_location('sd', '/tmp/vis/app/survey_def.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.public_definition()


def event(Obj, v=''):
    short = v == 'short'
    return Obj(id=42, name='Feria Pyme' if short else LONG_EVENT, event_code='CNIT26', tenant=Obj(name='Acme' if short else LONG_TENANT, id='acme'),
               status='creado' if v == 'creado' else 'en_proceso', queue_enabled=v != 'off', facial_enabled=False, selfreg_enabled=True, areas_enabled=True,
               certificates_enabled=True, inventory_enabled=True, report_pdf_path=None, local_node_name='Portátil Sala 3' if v == 'local' else None,
               local_last_upload_at=datetime.datetime(2026, 11, 9, 14, 30) if v == 'local' else None, auto_print_badge=False, auto_register=False,
               directory_page_size=50, face_door_enabled=False, reprint_disabled=False, shared_print_enabled=False, brand_color='', logo_mode='golden', logo_path=None,
               categories=[], digital_badge_enabled=True, idle_minutes=30, controller_mode='golden', consent_prompt_mode='screen', organizer_name='Acme S.A.S.',
               organizer_nit='900123456-7', organizer_privacy_email='privacidad@ejemplo.test', precalculo_anexo_fecha=None, precalculo_anexo_ref='', precalculo_autorizado=False,
               precalculo_garantia='', accept_link_email=False, accept_no_birth_mode='', aceptar_enabled=False, badge_bio_photo_allowed=False, client_photos_before=False,
               logo_fit='contain', logo_height=40, get_optional_labels=lambda: {})


def staff(role='admin'):
    return {'staff_name': LONG_STAFF, 'staff_role': role, 'staff_id': 7}


def kiosk_ctx(Obj, v):
    ev = event(Obj, v)
    return {**staff('cliente' if v == 'cliente' else 'admin'), 'event': ev, 'optional_labels': [], 'optional_labels_json': '[]', 'field_configs': FIELD_CONFIGS,
            'field_configs_json': json.dumps(FIELD_CONFIGS), 'field_labels': {c['key']: c['label'] for c in FIELD_CONFIGS}, 'sidebar_active': 'eventos',
            'contingency_enabled': False, 'registro_gear': True, 'search_unified': True, 'person_form_json': 'null', 'person_form_env': False, 'person_form_can_design': False,
            'idle_general_minutes': 30, 'reprint_approval_minutes': 10, 'registro_gear_dig': False, 'last_name_state': {}, 'brand_default': '#d4af37'}


def context(key, v, Obj):
    ev = event(Obj, v)
    simple = {**staff(), 'sidebar_active': '', 'crm_nav': [{'key': k, 'label': l, 'href': h} for k, l, h, _a in _CRM_SECTIONS]}
    if key in ('kiosk_registro', 'kiosk_select', 'kiosk_turnos', 'kiosk_turnos_tv', 'kiosk_expositores', 'kiosk_autoregistro', 'kiosk_parametros', 'kiosk_formularios', 'kiosk_usuarios'):
        return key + '.html', kiosk_ctx(Obj, v)
    if key == 'kiosk_tv':
        return 'kiosk_tv.html', {'event': ev, 'tv_api': '/api/events/42/tv', 'logo_url': '', 'brand_css': '', 'poll_s': 10}
    if key == 'turno_public':
        return 'turno_public.html', {'event_id': 42, 'event_name': ev.name, 'token': '' if v in ('', 'ask', 'short') else 'tok' + v}
    if key in ('contact_card', 'contact_manage', 'expositor'):
        return key + '.html', {'token': 'tk-' + (v or 'ok'), 'event': ev, 'event_name': ev.name, 'available': v != 'gone', 'exhibitor_name': 'Industrias Metalmecánicas del Pacífico Ltda.' if v != 'short' else 'Café Sol',
                               'logo_url': '', 'brand_css': ''}
    if key == 'entrega':
        if v == 'gone':
            return 'entrega.html', {'unavailable': 'Este enlace ya venció. Pídale uno nuevo a su asesor comercial.', 'event_name': '', 'company': '', 'event_date': '', 'survey': None, 'state': None}
        return 'entrega.html', {'unavailable': '', 'event_name': ev.name, 'company': ev.tenant.name, 'event_date': '12/11/2026', 'survey': survey(),
                                'state': {'survey_done': v in ('done', 'nodb'), 'has_db': v != 'nodb'}, 'download_url': '/entrega/x/base', 'submit_url': '/entrega/x/encuesta'}
    if key == 'servidor_local':
        return 'servidor_local.html', {**simple, 'sidebar_active': 'servidor_local', '__local_server': True}
    if key == 'sincronizacion':
        return 'sincronizacion.html', {**simple, 'sidebar_active': 'sincronizacion', 'local_server': v == 'local', '__local_server': v == 'local'}
    if key == 'cuentas_cobro':
        return 'cuentas_cobro.html', {**simple, 'sidebar_active': 'cuentas_cobro'}
    if key == 'gastos':
        return 'gastos.html', {**simple, 'sidebar_active': 'gastos', 'has_eventos_js': True}
    if key == 'inventario':
        return 'inventario.html', {**simple, 'sidebar_active': 'inventario'}
    if key == 'configuracion':
        return 'configuracion.html', {**simple, 'staff_role': 'super_admin', 'sidebar_active': 'configuracion', 'request': Obj(session={'staff_role': 'super_admin'}, query_params={}, base_url='https://app.ejemplo.test/')}
    if key == 'staff':
        return 'staff.html', {**simple, 'sidebar_active': 'configuracion'}
    if key == 'dashboard':
        return 'dashboard.html', {**staff('digitador')}
    if key == 'login':
        return 'login.html', {'error': 'Usuario o contraseña incorrectos.' if v == 'err' else None, 'notice': None}
    if key == 'digital_badge':
        return 'digital_badge.html', {'token': 'tok'}
    if key == 'eventos':
        return 'eventos.html', {**simple, 'sidebar_active': 'eventos'}
    if key == 'nuevo_evento':
        return 'nuevo_evento.html', {**simple, 'sidebar_active': 'eventos', 'pure_coordinator': False, 'tenant_id': '', 'tenant_name': '', 'pick_tenant': True, 'back_url': '/eventos'}
    if key == 'plantilla_evento':
        return 'plantilla_evento.html', {**simple, 'sidebar_active': 'configuracion'}
    if key == 'crm_cuentas':
        return 'crm_cuentas.html', {**simple, 'staff_role': 'admin', 'sidebar_active': 'crm', 'can_admin': v != 'comercial'}
    if key == 'crm_cuenta':
        return 'crm_cuenta.html', {**simple, 'sidebar_active': 'crm', 'can_admin': v != 'comercial', 'account_id': '' if v == 'new' else 1}
    ext = _extensions(key, v, Obj, simple)          # pantallas de otras piezas (pages_<pieza>.py); así cada pieza trae su archivo y no se pisan
    if ext is not None:
        return ext
    raise KeyError(key)


def _extensions(key, v, Obj, simple):
    """Cada `scripts/visual_harness/pages_*.py` define `context(key, v, Obj, simple)` y devuelve (plantilla, contexto) o None si la pantalla no es suya."""
    import glob
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    for path in sorted(glob.glob(os.path.join(here, 'pages_*.py'))):
        spec = importlib.util.spec_from_file_location(os.path.basename(path)[:-3], path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        got = mod.context(key, v, Obj, simple)
        if got is not None:
            return got
    return None
