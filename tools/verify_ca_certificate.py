"""Check a database CA certificate file against the live PostgreSQL server in DATABASE_URL.

Usage:  python tools/verify_ca_certificate.py config/prod-ca-2021.crt

Prints the certificate's subject and SHA-256 fingerprint, then performs a fully verified TLS
handshake (certificate chain + hostname) with the server. Read-only: no database login happens.
"""
import socket
import ssl
import struct
import sys
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.settings import database_url, verified_context  # noqa: E402

SSL_REQUEST = struct.pack("!ii", 8, 80877103)   # PostgreSQL's "please switch to TLS" message


def main(ca_file):
    path = Path(ca_file)
    if not path.is_file():
        sys.exit(f"File not found: {ca_file}")
    for cert in x509.load_pem_x509_certificates(path.read_bytes()):
        print(f"CA file certificate : {cert.subject.rfc4514_string()}")
        print(f"  valid             : {cert.not_valid_before_utc:%Y-%m-%d} -> {cert.not_valid_after_utc:%Y-%m-%d}")
        print(f"  SHA-256           : {cert.fingerprint(hashes.SHA256()).hex(':').upper()}")

    url = database_url((dotenv_values(Path(__file__).resolve().parents[1] / ".env").get("DATABASE_URL") or "").strip())
    host, port = urlsplit(url).hostname, urlsplit(url).port or 5432
    context = verified_context(str(path))      # the same context the app uses: chain + expiry + hostname
    with socket.create_connection((host, port), timeout=15) as raw:
        raw.sendall(SSL_REQUEST)
        if raw.recv(1) != b"S":
            sys.exit("The server did not accept TLS.")
        try:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                print(f"\nVERIFIED: {host} presented a certificate chain trusted by this CA file "
                      f"and valid for this hostname ({tls.version()}).")
        except ssl.SSLCertVerificationError as exc:
            sys.exit(f"\nNOT VERIFIED: {exc.verify_message}.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
