"""Blocks requests to private network addresses (cloud metadata, internal services)."""
from __future__ import annotations

import ipaddress
import socket


def is_public_host(host: str) -> bool:
    """False if the host resolves to a private address. Unresolvable hosts are left to the browser to fail."""
    try:
        ip = ipaddress.ip_address(host.strip('[]'))
        infos = [(None, None, None, None, (str(ip),))]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return True
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True
