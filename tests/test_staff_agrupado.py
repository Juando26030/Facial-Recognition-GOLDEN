"""Staff (17-nov-2026): la lista se agrupa por rol en paneles desplegables; quien tiene doble rol sale en los dos; al buscar, lista plana."""
import pathlib

JS = pathlib.Path(__file__).resolve().parent.parent / "static/js/gw-staff.js"


def test_staff_list_is_grouped_by_role_and_flat_when_searching():
    js = JS.read_text(encoding="utf-8")
    assert "details class=\"gw-group gw-staff__group\"" in js and "GROUP_ORDER" in js and "Coordinadores" in js
    assert "rolesOf = (s) => [s.role].concat(s.extra_roles" in js            # el doble rol cae en cada grupo
    assert "if (searchTerm) { setLayout(false);" in js                       # buscando: sin paneles
    assert "openGroups" in js                                                # los paneles abiertos se conservan al recargar
