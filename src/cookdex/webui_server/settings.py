from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import ipaddress
import os
import socket
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from ..config import REPO_ROOT

DEFAULT_BASE_PATH = "/cookdex"
DEFAULT_DB_PATH = "cache/webui/state.db"
DEFAULT_BIND_HOST = "0.0.0.0"
DEFAULT_BIND_PORT = 4820
DEFAULT_SESSION_TTL_SECONDS = 43_200
DEFAULT_BOOTSTRAP_USER = "admin"
DEFAULT_COOKIE_NAME = "mo_webui_session"
DEFAULT_MAX_LOG_FILES = 200
_WEAK_MASTER_KEYS = frozenset({"replace-with-strong-master-key", "changeme", "secret", ""})


@dataclass(frozen=True)
class WebUISettings:
    bind_host: str
    bind_port: int
    base_path: str
    state_db_path: Path
    session_ttl_seconds: int
    bootstrap_user: str
    bootstrap_password: str
    fernet_key: str
    cookie_name: str
    cookie_secure: bool
    static_dir: Path
    web_dist_dir: Path
    logs_dir: Path
    config_root: Path
    max_log_files: int
    weak_master_key: bool
    ssl_enabled: bool
    ssl_certfile: Path | None
    ssl_keyfile: Path | None


def _normalize_base_path(raw: str) -> str:
    base = raw.strip() or DEFAULT_BASE_PATH
    if not base.startswith("/"):
        base = f"/{base}"
    return base.rstrip("/") or DEFAULT_BASE_PATH


def _normalize_fernet_key(raw: str) -> str:
    candidate = raw.strip()
    if not candidate:
        raise RuntimeError("Encryption key value is empty.")
    try:
        Fernet(candidate.encode("utf-8"))
        return candidate
    except Exception:
        digest = hashlib.sha256(candidate.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).decode("utf-8")


def _load_master_key(state_db_path: Path) -> tuple[str, bool]:
    # Priority 1: explicit env var
    value = os.environ.get("MO_WEBUI_MASTER_KEY", "").strip()
    if value:
        is_weak = value.lower() in _WEAK_MASTER_KEYS
        if is_weak:
            print(
                "[webui] WARNING: MO_WEBUI_MASTER_KEY is set to a weak default. "
                "Replace it with a strong random value to protect encrypted secrets.",
                flush=True,
            )
        return _normalize_fernet_key(value), is_weak

    # Priority 2: key file env var
    key_file = os.environ.get("MO_WEBUI_MASTER_KEY_FILE", "").strip()
    if key_file:
        path = Path(key_file).expanduser().resolve()
        if not path.exists():
            raise RuntimeError(f"MO_WEBUI_MASTER_KEY_FILE does not exist: {path}")
        return _normalize_fernet_key(path.read_text(encoding="utf-8").strip()), False

    # Priority 3: auto-generate and persist alongside the state DB
    auto_key_path = state_db_path.parent / ".master_key"
    if auto_key_path.exists():
        return _normalize_fernet_key(auto_key_path.read_text(encoding="utf-8").strip()), False

    auto_key_path.parent.mkdir(parents=True, exist_ok=True)
    new_key = Fernet.generate_key().decode("utf-8")
    auto_key_path.write_text(new_key, encoding="utf-8")
    try:
        auto_key_path.chmod(0o600)
    except OSError:
        pass
    print(f"[webui] auto-generated encryption key at {auto_key_path}", flush=True)
    return new_key, False


def _int_env(name: str, default: int, *, min_val: int | None = None, max_val: int | None = None) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if min_val is not None and value < min_val:
        print(f"[webui] WARNING: {name}={value} is below minimum {min_val}, using {min_val}", flush=True)
        return min_val
    if max_val is not None and value > max_val:
        print(f"[webui] WARNING: {name}={value} is above maximum {max_val}, using {max_val}", flush=True)
        return max_val
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def _ensure_ssl_cert(state_db_path: Path) -> tuple[Path, Path]:
    """Return (certfile, keyfile), generating a self-signed pair if needed."""
    cert_dir = state_db_path.parent
    cert_path = cert_dir / "self-signed.crt"
    key_path = cert_dir / "self-signed.key"

    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    cert_dir.mkdir(parents=True, exist_ok=True)

    private_key = ec.generate_private_key(ec.SECP256R1())

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CookDex Self-Signed"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])

    san_entries: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        x509.IPAddress(ipaddress.IPv6Address("::1")),
    ]
    try:
        hostname = socket.gethostname()
        if hostname and hostname != "localhost":
            san_entries.append(x509.DNSName(hostname))
    except OSError:
        pass

    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + _dt.timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName(san_entries),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    try:
        key_path.chmod(0o600)
    except OSError:
        pass

    print(f"[webui] auto-generated self-signed TLS certificate at {cert_path}", flush=True)
    return cert_path, key_path


def load_webui_settings() -> WebUISettings:
    bind_host = os.environ.get("WEB_BIND_HOST", DEFAULT_BIND_HOST).strip() or DEFAULT_BIND_HOST
    bind_port = _int_env("WEB_BIND_PORT", DEFAULT_BIND_PORT, min_val=1, max_val=65535)
    base_path = _normalize_base_path(os.environ.get("WEB_BASE_PATH", DEFAULT_BASE_PATH))
    db_raw = os.environ.get("WEB_STATE_DB_PATH", DEFAULT_DB_PATH).strip() or DEFAULT_DB_PATH
    state_db_path = Path(db_raw)
    if not state_db_path.is_absolute():
        state_db_path = REPO_ROOT / state_db_path
    state_db_path = state_db_path.resolve()

    logs_dir = REPO_ROOT / "logs" / "webui" / "runs"
    static_dir = Path(__file__).resolve().parent / "static"
    web_dist_dir = (REPO_ROOT / "web" / "dist").resolve()
    config_root_raw = os.environ.get("WEB_CONFIG_ROOT", "").strip()
    if config_root_raw:
        config_root = Path(config_root_raw)
        if not config_root.is_absolute():
            config_root = (REPO_ROOT / config_root).resolve()
    else:
        config_root = REPO_ROOT

    session_ttl = _int_env("WEB_SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS, min_val=60)
    bootstrap_user = os.environ.get("WEB_BOOTSTRAP_USER", DEFAULT_BOOTSTRAP_USER).strip() or DEFAULT_BOOTSTRAP_USER
    bootstrap_password = os.environ.get("WEB_BOOTSTRAP_PASSWORD", "").strip()
    cookie_name = os.environ.get("WEB_SESSION_COOKIE_NAME", DEFAULT_COOKIE_NAME).strip() or DEFAULT_COOKIE_NAME
    max_log_files = _int_env("WEB_MAX_LOG_FILES", DEFAULT_MAX_LOG_FILES, min_val=1)
    fernet_key, weak_master_key = _load_master_key(state_db_path)

    # --- SSL / TLS ---
    ssl_enabled = _bool_env("WEB_SSL", True)
    ssl_certfile: Path | None = None
    ssl_keyfile: Path | None = None

    if ssl_enabled:
        user_cert = os.environ.get("WEB_SSL_CERTFILE", "").strip()
        user_key = os.environ.get("WEB_SSL_KEYFILE", "").strip()
        if user_cert and user_key:
            ssl_certfile = Path(user_cert).resolve()
            ssl_keyfile = Path(user_key).resolve()
            if not ssl_certfile.exists():
                raise RuntimeError(f"WEB_SSL_CERTFILE does not exist: {ssl_certfile}")
            if not ssl_keyfile.exists():
                raise RuntimeError(f"WEB_SSL_KEYFILE does not exist: {ssl_keyfile}")
        elif user_cert or user_key:
            raise RuntimeError("Both WEB_SSL_CERTFILE and WEB_SSL_KEYFILE must be set together.")
        else:
            ssl_certfile, ssl_keyfile = _ensure_ssl_cert(state_db_path)

    # Default cookie_secure to match SSL state unless explicitly overridden
    cookie_secure_raw = os.environ.get("WEB_COOKIE_SECURE", "").strip().lower()
    if cookie_secure_raw:
        cookie_secure = cookie_secure_raw not in {"0", "false", "no", "off"}
    else:
        cookie_secure = ssl_enabled

    return WebUISettings(
        bind_host=bind_host,
        bind_port=bind_port,
        base_path=base_path,
        state_db_path=state_db_path,
        session_ttl_seconds=session_ttl,
        bootstrap_user=bootstrap_user,
        bootstrap_password=bootstrap_password,
        fernet_key=fernet_key,
        cookie_name=cookie_name,
        cookie_secure=cookie_secure,
        static_dir=static_dir,
        web_dist_dir=web_dist_dir,
        logs_dir=logs_dir,
        config_root=config_root,
        max_log_files=max_log_files,
        weak_master_key=weak_master_key,
        ssl_enabled=ssl_enabled,
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
    )
