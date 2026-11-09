"""F5-9 (revisión de seguridad A): instalador y actualizador de Windows del servidor local y certificados. Sin Windows: se revisa el texto de los scripts y la lógica pura."""
import datetime
import importlib.util
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parent.parent
WIN = SRC / "deploy" / "windows"


def test_install_cuts_inherited_write_access_to_the_folder_run_as_system():
    """A-03: C:\\GoldenLocal no hereda «Modificar» de Usuarios autenticados (scripts y app corren como SYSTEM)."""
    src = (WIN / "install.ps1").read_text(encoding="utf-8")
    assert "icacls $Root /inheritance:r /grant:r 'SYSTEM:(OI)(CI)F' 'BUILTIN\\Administrators:(OI)(CI)F'" in src
    assert "BUILTIN\\Users:(OI)(CI)RX" in src and "BUILTIN\\Users:(OI)(CI)M" not in src
    assert src.index("/inheritance:r") < src.index("# ---- 1.")


def test_updater_trusts_production_not_the_request_file():
    """A-04: el actualizador (SYSTEM) vuelve a pedir el manifiesto a producción y descarga lo publicado, no la dirección/huella escrita en update-request.json."""
    src = (WIN / "run-update.ps1").read_text(encoding="utf-8")
    assert "/api/ops/update-manifest" in src and "-MaximumRedirection 0" in src
    assert "Invoke-WebRequest -Uri $pkgUrl" in src and "$hash -ne $pkgSha" in src
    assert "Invoke-WebRequest -Uri $req.package_url" not in src
    assert src.index("update-manifest") < src.index("Backup-Database")


def _gen_cert():
    pytest.importorskip("cryptography")
    spec = importlib.util.spec_from_file_location("gen_cert_f59", WIN / "gen_cert.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_local_ca_can_only_sign_local_names(tmp_path):
    """A-11: la autoridad que se instala en Windows y en los celulares lleva restricciones de nombre: con su llave no se suplanta un sitio de internet."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID
    gc = _gen_cert()
    gc.make(tmp_path, "LAPTOP-GOLDEN", ["192.168.1.10"])
    ca = x509.load_pem_x509_certificate((tmp_path / "ca.pem").read_bytes())
    nc = ca.extensions.get_extension_for_class(x509.NameConstraints)
    assert nc.critical
    permitted = {str(s.value) for s in nc.value.permitted_subtrees}
    assert {"laptop-golden", "golden.local", "localhost", "192.168.0.0/16", "10.0.0.0/8"} <= permitted
    server = x509.load_pem_x509_certificate((tmp_path / "server.pem").read_bytes())
    server.verify_directly_issued_by(ca)
    # un certificado para un sitio de internet firmado con la llave robada: viola las restricciones (lo rechazan Chrome, Android, iOS y OpenSSL)
    key = serialization.load_pem_private_key((tmp_path / "ca.key").read_bytes(), None)
    now = datetime.datetime.now(datetime.timezone.utc)
    leaf_key = gc._key()
    forged = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "www.example.com")])).issuer_name(ca.subject)
              .public_key(leaf_key.public_key()).serial_number(1).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
              .add_extension(x509.SubjectAlternativeName([x509.DNSName("www.example.com")]), critical=False).sign(key, hashes.SHA256()))
    try:
        from cryptography.x509.verification import PolicyBuilder, Store, VerificationError
    except ImportError:
        return
    verifier = PolicyBuilder().store(Store([ca])).time(now).build_server_verifier(x509.DNSName("www.example.com"))
    with pytest.raises(VerificationError):
        verifier.verify(forged, [])
