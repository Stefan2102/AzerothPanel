"""Certificates for the remote (HTTPS) listener.

Either the user's own certificate + key files (e.g. from Let's Encrypt via win-acme),
or a self-signed certificate the panel creates in data/tls/. The self-signed one
covers localhost, this PC's name and its IPv4 addresses; browsers show a one-time
warning for it, and the SHA-256 fingerprint shown in Settings lets you verify it.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import socket
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from ..paths import TLS_DIR
from ..settings import Settings

SELF_CERT = TLS_DIR / "self-signed.crt"
SELF_KEY = TLS_DIR / "self-signed.key"


class TlsError(Exception):
    pass


def host_names() -> tuple[list[str], list[str]]:
    """(DNS names, IPv4 addresses) this PC is reachable under."""
    name = socket.gethostname()
    dns = sorted({"localhost", name, name.lower()})
    try:
        ips = set(socket.gethostbyname_ex(name)[2])
    except OSError:
        ips = set()
    ips.add("127.0.0.1")
    return dns, sorted(ips, key=lambda a: tuple(int(p) for p in a.split(".")))


def generate_self_signed() -> None:
    TLS_DIR.mkdir(parents=True, exist_ok=True)
    dns, ips = host_names()
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AzerothPanel"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AzerothPanel (self-signed)")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=5 * 365))
        .add_extension(x509.SubjectAlternativeName(
            [x509.DNSName(d) for d in dns] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    SELF_KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    SELF_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def paths(settings: Settings) -> tuple[Path, Path]:
    """Certificate and key the listener uses (creates the self-signed pair if needed)."""
    if settings.tls_cert or settings.tls_key:
        cert, key = Path(settings.tls_cert), Path(settings.tls_key)
        if not cert.is_file() or not key.is_file():
            raise TlsError("Certificate or key file not found.")
        return cert, key
    if not SELF_CERT.is_file() or not SELF_KEY.is_file():
        generate_self_signed()
    return SELF_CERT, SELF_KEY


def validate(cert: Path, key: Path) -> None:
    """Fail early with a readable message instead of at panel start."""
    try:
        ssl.create_default_context(ssl.Purpose.CLIENT_AUTH).load_cert_chain(str(cert), str(key))
    except (ssl.SSLError, OSError) as exc:
        raise TlsError(f"Certificate and key don't load together: {exc}") from exc


def describe(cert_path: Path) -> dict:
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names = [str(v) for v in san.get_values_for_type(x509.DNSName)] + \
                [str(v) for v in san.get_values_for_type(x509.IPAddress)]
    except x509.ExtensionNotFound:
        names = []
    fp = cert.fingerprint(hashes.SHA256()).hex().upper()
    return {
        "subject": cert.subject.rfc4514_string(),
        "self_signed": cert.issuer == cert.subject,
        "names": names,
        "expires": cert.not_valid_after_utc.timestamp(),
        "fingerprint": ":".join(fp[i:i + 2] for i in range(0, len(fp), 2)),
    }
