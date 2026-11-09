"""Certificados HTTPS para la red local (Fase 6, docs/17 §2): una autoridad propia («Golden Local CA») y un certificado del servidor firmado por ella.

Uso:  python gen_cert.py <carpeta_destino> <nombre_equipo> [ip ...]
Escribe: ca.pem / GoldenLocal-CA.cer (la autoridad: se instala en Windows y se entrega a los celulares), server.pem y server.key (los usa la app).
El certificado cubre el nombre del equipo, «golden.local», localhost y las IP que se pasen. Dura 825 días (límite que aceptan los celulares); el instalador lo renueva si vence en < 60 días.
Usa `cryptography` (ya es dependencia de la app: cifrado del rostro).
"""
import datetime
import ipaddress
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

VALID_DAYS = 825
# F5-9 A-11: la llave de la autoridad vive en el portátil y la autoridad se instala en Windows y en los celulares. Con «restricciones de nombre» solo puede firmar
# certificados para la red local (el nombre del equipo, golden.local, localhost y direcciones privadas): si alguien se roba ca.key NO puede suplantar sitios de internet.
PRIVATE_NETS = ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")


def name_constraints(host: str) -> x509.NameConstraints:
    dns = []
    for n in (host, "golden.local", "localhost"):
        n = (n or "").strip().lower()
        if n and n not in dns:
            dns.append(n)
    return x509.NameConstraints(permitted_subtrees=[x509.DNSName(n) for n in dns] + [x509.IPAddress(ipaddress.ip_network(c)) for c in PRIVATE_NETS], excluded_subtrees=None)


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem_key(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())


def san_entries(host: str, ips: list) -> list:
    names = []
    for n in (host, "golden.local", "localhost"):
        if n and n not in names:
            names.append(n)
    out = [x509.DNSName(n) for n in names]
    for ip in ["127.0.0.1", *ips]:
        try:
            out.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            continue
    return out


def make(folder: Path, host: str, ips: list) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    ca_path = folder / "ca.pem"
    if ca_path.exists() and (folder / "ca.key").exists():          # la autoridad se conserva: así los celulares que ya la instalaron no tienen que repetirlo
        ca_cert = x509.load_pem_x509_certificate(ca_path.read_bytes())
        ca_key = serialization.load_pem_private_key((folder / "ca.key").read_bytes(), None)
    else:
        ca_key = _key()
        name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Golden Eventos y Logistica S.A.S."), x509.NameAttribute(NameOID.COMMON_NAME, "Golden Local CA")])
        ca_cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=3650))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                   .add_extension(name_constraints(host), critical=True)
                   .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False, key_encipherment=False, data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
                   .sign(ca_key, hashes.SHA256()))
        ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
        (folder / "ca.key").write_bytes(_pem_key(ca_key))
        (folder / "GoldenLocal-CA.cer").write_bytes(ca_cert.public_bytes(serialization.Encoding.DER))
    key = _key()
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host or "golden.local")])).issuer_name(ca_cert.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
            .add_extension(x509.SubjectAlternativeName(san_entries(host, ips)), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    (folder / "server.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))
    (folder / "server.key").write_bytes(_pem_key(key))
    return {"not_after": cert.not_valid_after_utc.isoformat(), "names": [str(e.value) for e in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value]}


def days_left(server_pem: Path) -> int:
    cert = x509.load_pem_x509_certificate(server_pem.read_bytes())
    return (cert.not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc)).days


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("Uso: python gen_cert.py <carpeta> <nombre_equipo> [ip ...]")
    print(make(Path(sys.argv[1]), sys.argv[2], sys.argv[3:]))
