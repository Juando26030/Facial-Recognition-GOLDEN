"""IP que el servidor local muestra para conectar otros equipos (20-nov-2026): la del adaptador REAL que está usando (fija o automática), no la de uno virtual.
Pruebas puras (corren con `pytest --noconftest`): sin Windows, sin red."""
from app import localmode


def R(ip, alias, gw=False, desc=""):
    return {"ip": ip, "alias": alias, "gateway": gw, "desc": desc}


def test_real_adapter_with_gateway_beats_virtual_ones():
    rows = [R("172.28.208.1", "vEthernet (WSL)", False, "Hyper-V Virtual Ethernet Adapter"),
            R("192.168.1.45", "Ethernet", True, "Realtek PCIe GbE"),
            R("10.0.75.1", "VirtualBox Host-Only Network", False, "VirtualBox Host-Only Ethernet Adapter")]
    assert localmode.rank_adapters(rows) == ["192.168.1.45"]


def test_wired_before_wifi_and_gateway_before_no_gateway():
    rows = [R("192.168.1.50", "Wi-Fi", True, "Intel Wireless"), R("192.168.1.45", "Ethernet", True, "Realtek"), R("10.1.1.5", "Ethernet 2", False, "USB")]
    assert localmode.rank_adapters(rows) == ["192.168.1.45", "192.168.1.50", "10.1.1.5"]


def test_static_address_without_gateway_is_still_shown():
    assert localmode.rank_adapters([R("192.168.0.20", "Ethernet", False, "Realtek")]) == ["192.168.0.20"]


def test_virtual_only_is_used_when_there_is_nothing_else():
    assert localmode.rank_adapters([R("192.168.56.1", "VirtualBox Host-Only Network", False, "VirtualBox")]) == ["192.168.56.1"]


def test_discards_loopback_link_local_and_garbage():
    rows = [R("127.0.0.1", "Loopback"), R("169.254.3.4", "Ethernet"), R("no-es-ip", "Ethernet"), R("192.168.1.9", "Ethernet", True)]
    assert localmode.rank_adapters(rows) == ["192.168.1.9"]
    assert localmode.rank_adapters([]) == []


def test_not_windows_falls_back_to_socket_probe_without_crashing():
    assert localmode._windows_adapters() is None or isinstance(localmode._windows_adapters(), list)
    assert isinstance(localmode.lan_addresses(), list)


def test_details_say_which_connection_each_address_uses():
    """24-nov-2026: cable + Wi‑Fi de otra red (caso real del evento): la del cable primero y cada una con su tipo."""
    rows = [R("192.168.0.33", "Wi-Fi 2", True, "Intel Wireless"), R("192.168.1.127", "Ethernet", True, "Realtek PCIe GbE"),
            R("172.28.208.1", "vEthernet (WSL)", False, "Hyper-V Virtual Ethernet Adapter")]
    assert localmode.rank_adapter_details(rows) == [{"ip": "192.168.1.127", "kind": "cable"}, {"ip": "192.168.0.33", "kind": "wifi"}]
    assert localmode.rank_adapter_details([R("192.168.0.33", "Wi-Fi 2", True, "Intel Wireless")]) == [{"ip": "192.168.0.33", "kind": "wifi"}]
    assert [d["ip"] for d in localmode.rank_adapter_details(rows)] == localmode.rank_adapters(rows)
    assert isinstance(localmode.lan_address_details(), list)


def test_banner_shows_connection_kind_and_warns_without_cable():
    import pathlib
    js = (pathlib.Path(__file__).resolve().parents[1] / "static/js/version-banner.js").read_text(encoding="utf-8")
    assert "Sin cable al router" in js and "a.details" in js and "gw-vb-more" in js
