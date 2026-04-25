from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse, urlunparse

import requests

_BLOCKED_METADATA_HOSTS = {"metadata.google.internal"}
_BLOCKED_METADATA_IPS = {
    ipaddress.ip_address("168.63.129.16"),  # Azure metadata
    ipaddress.ip_address("100.100.100.200"),  # Alibaba Cloud metadata
}


def validate_service_url(url: str, *, allow_private: bool = False) -> str:
    """Validate a server-side request URL and return a normalized equivalent."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https.")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL must include a hostname.")
    if host in _BLOCKED_METADATA_HOSTS:
        raise ValueError("Requests to cloud metadata endpoints are not allowed.")

    try:
        addr_info = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve hostname: {host}") from exc

    for _family, _socktype, _proto, _canonname, sockaddr in addr_info:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip in _BLOCKED_METADATA_IPS:
            raise ValueError("Requests to cloud metadata endpoints are not allowed.")
        if ip.is_link_local:
            raise ValueError("Requests to link-local addresses are not allowed.")
        if not allow_private and (ip.is_private or ip.is_loopback or ip.is_reserved):
            raise ValueError("Requests to private/internal addresses are not allowed.")

    return urlunparse(parsed)


def request_with_url_validation(
    session: requests.Session,
    method: str,
    url: str,
    *,
    allow_private: bool = False,
    max_redirects: int = 5,
    **kwargs,
) -> requests.Response:
    """Issue an HTTP request, validating the initial URL and each redirect hop."""
    current_url = validate_service_url(url, allow_private=allow_private)
    kwargs.pop("allow_redirects", None)

    for _redirect_count in range(max_redirects + 1):
        response = session.request(method, current_url, allow_redirects=False, **kwargs)
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response

        location = response.headers.get("location", "").strip()
        if not location:
            return response

        current_url = validate_service_url(urljoin(current_url, location), allow_private=allow_private)
        if response.status_code == 303 and method.upper() != "HEAD":
            method = "GET"

    raise requests.TooManyRedirects(f"Exceeded {max_redirects} redirects for {url}")
