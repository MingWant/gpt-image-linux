import ipaddress
import socket
from typing import List, Tuple
from urllib.parse import urlparse


def _get_private_ip_ranges() -> List[Tuple[ipaddress.IPv4Network, ...]]:
    return [
        (ipaddress.IPv4Network("127.0.0.0/8"),),  # loopback
        (ipaddress.IPv4Network("10.0.0.0/8"),),  # private Class A
        (ipaddress.IPv4Network("172.16.0.0/12"),),  # private Class B
        (ipaddress.IPv4Network("192.168.0.0/16"),),  # private Class C
        (ipaddress.IPv4Network("169.254.0.0/16"),),  # link-local
        (ipaddress.IPv4Network("0.0.0.0/8"),),  # current network
        (ipaddress.IPv4Network("224.0.0.0/4"),),  # multicast IPv4
        (ipaddress.IPv4Network("255.255.255.255/32"),),  # broadcast
        (ipaddress.IPv6Network("::1/128"),),  # loopback
        (ipaddress.IPv6Network("fc00::/7"),),  # unique local
        (ipaddress.IPv6Network("fe80::/10"),),  # link-local
        (ipaddress.IPv6Network("::ffff:0:0/96"),),  # IPv4-mapped
        (ipaddress.IPv6Network("ff00::/8"),),  # multicast IPv6
    ]


PRIVATE_RANGES = _get_private_ip_ranges()

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.google.com",
    "169.254.169.254",
    "metadata.azure.com",
    "metadata.internal",
    "detectportal.safari.com",
    "captive.apple.com",
}


def is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True

    for private_range in PRIVATE_RANGES:
        for network in private_range:
            if isinstance(network, ipaddress.IPv6Network):
                if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                    ip = ipaddress.IPv4Address(str(ip.ipv4_mapped))
            if ip in network:
                return True
    return False


def resolve_hostname(hostname: str) -> Tuple[str, List[str]]:
    try:
        family = socket.AF_UNSPEC
        addrs = socket.getaddrinfo(hostname, None, family, socket.SOCK_STREAM)
    except socket.gaierror:
        return hostname, []

    resolved_ips = []
    for addr in addrs:
        ip = addr[4][0]
        resolved_ips.append(ip)
    return hostname, list(dict.fromkeys(resolved_ips))


def validate_upstream_url(url: str, allowlist: str) -> None:
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise ValueError("Only HTTPS URLs are allowed for upstream API")

    if not parsed.hostname:
        raise ValueError("Invalid URL: no hostname")

    hostname = parsed.hostname.lower()

    if hostname in BLOCKED_HOSTNAMES:
        raise ValueError(f"Hostname '{hostname}' is not allowed")

    if allowlist:
        allowed_hosts = [h.strip().lower() for h in allowlist.split(",") if h.strip()]
        if hostname not in allowed_hosts:
            raise ValueError(
                f"Hostname '{hostname}' is not in the allowlist. Allowed: {', '.join(allowed_hosts)}"
            )

    _, resolved_ips = resolve_hostname(hostname)
    for ip in resolved_ips:
        if is_private_ip(ip):
            resolved_info = ", ".join(f"'{ip}'" for ip in resolved_ips)
            raise ValueError(
                f"Hostname '{hostname}' resolves to private/internal IP(s): {resolved_info}"
            )


def validate_image_url(url: str) -> None:
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only HTTP/HTTPS URLs are allowed for image URLs")

    if not parsed.hostname:
        raise ValueError("Invalid URL: no hostname")

    hostname = parsed.hostname.lower()

    if hostname in BLOCKED_HOSTNAMES:
        raise ValueError(f"Hostname '{hostname}' is not allowed")

    _, resolved_ips = resolve_hostname(hostname)
    for ip in resolved_ips:
        if is_private_ip(ip):
            resolved_info = ", ".join(f"'{ip}'" for ip in resolved_ips)
            raise ValueError(
                f"Image URL hostname '{hostname}' resolves to private/internal IP(s): {resolved_info}"
            )