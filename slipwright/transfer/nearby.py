"""Finding the other Slipwrights on this network.

No multicast and no broadcast: an installation in Docker sits on a bridge network that
neither reaches, and Docker is how most of them run. What does get out of a container is
an ordinary TCP connection, so the network is looked at the way ``slipwright worker``
looks for its server: a connect to every host of a /24 on the ports Slipwright listens
on, many at once, and a ``hello`` to the ones that answer.

Which /24 is the question. The page tells us best: a person who opened it at
``192.168.1.11:8500`` has said which network this machine is on and which port it answers
at, which a container cannot find out for itself. After that comes the address a Mac was
last given, then this machine's own outbound address -- right on a bare install, a bridge
address in Docker, where it finds nothing and costs a second.
"""

from __future__ import annotations

import ipaddress
import socket
import sys
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import httpx

#: Where Slipwright listens unless told otherwise.
DEFAULT_PORT = 8500
#: How many networks one look covers; each is 254 connects.
MAX_NETWORKS = 3
#: Looked at when nothing says which network this is -- a page opened at ``localhost``
#: on a server in Docker, which cannot see the network of the machine it runs on. These
#: are what home and office routers hand out; a guess, but one that is usually right.
USUAL_NETWORKS = ("192.168.1.0/24", "192.168.0.0/24", "10.0.0.0/24")
CONNECT_S = 0.4
HELLO_S = 2.0


def _private_v4(host: str | None) -> ipaddress.IPv4Address | None:
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return None
    if not isinstance(ip, ipaddress.IPv4Address) or ip.is_loopback or not ip.is_private:
        return None
    return ip


def in_container() -> bool:
    """Whether this runs in Docker, where its own address is the bridge's: 172.17.0.2
    says nothing about the network outside, and nobody there can reach it."""
    return Path("/.dockerenv").exists()


def own_address() -> str | None:
    """This machine's address on its network: the one a packet out would leave from. A
    UDP socket that is only connected sends nothing. None in a container (see above)."""
    if in_container():
        return None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # TEST-NET: never routed anywhere real
            me = str(probe.getsockname()[0])
    except OSError:
        return None
    return me if _private_v4(me) else None


def targets(*addresses: str | None, own: str | None = None) -> tuple[list[str], set[int]]:
    """(networks as ``a.b.c.0/24``, ports) worth looking at, best first."""
    networks: list[str] = []
    ports: set[int] = {DEFAULT_PORT}
    for address in addresses:
        if not address:
            continue
        parts = urlsplit(address if "://" in address else f"http://{address}")
        if parts.port:
            ports.add(parts.port)
        ip = _private_v4(parts.hostname)
        if ip is not None:
            net = str(ipaddress.ip_network(f"{ip}/24", strict=False))
            if net not in networks:
                networks.append(net)
    if own is not None:
        net = str(ipaddress.ip_network(f"{own}/24", strict=False))
        if net not in networks:
            networks.append(net)
    if not networks:
        networks.extend(USUAL_NETWORKS)
    return networks[:MAX_NETWORKS], ports


def _answers(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=CONNECT_S):
            return True
    except OSError:
        return False


def listening(networks: Iterable[str], ports: Iterable[int], skip: set[str]) -> list[str]:
    """``http://host:port`` of every host in ``networks`` that accepts a connection."""
    candidates = [
        (str(host), port)
        for net in networks
        for host in ipaddress.ip_network(net).hosts()
        for port in sorted(ports)
        if f"{host}:{port}" not in skip
    ]
    # Windows refuses more than 512 sockets in one select(); stay well under it
    workers = 64 if sys.platform == "win32" else 128
    with ThreadPoolExecutor(max_workers=workers) as pool:
        open_ = list(pool.map(lambda hp: _answers(*hp), candidates))
    return [f"http://{h}:{p}" for (h, p), ok in zip(candidates, open_, strict=True) if ok]


def hello(address: str, client: httpx.Client) -> dict[str, object] | None:
    """What a Slipwright at ``address`` says about itself, or None when it is not one.

    A release from before moving existed has no ``hello``, but is still worth showing --
    as one to update -- so it is recognised by the login page's public question, which
    nothing but Slipwright answers."""
    try:
        got = client.get(f"{address}/api/transfer/peer/hello", timeout=HELLO_S)
        found = got.json() if got.status_code == 200 else None
        if found is None and got.status_code == 404:
            first = client.get(f"{address}/api/auth/first-run", timeout=HELLO_S)
            if first.status_code == 200 and "default_admin" in first.json():
                host = urlsplit(address).hostname or address
                return {
                    "app": "slipwright",
                    "instance": address,
                    "name": host,
                    "version": "",
                    "revision": None,
                    "legacy": True,
                    "address": address,
                }
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(found, dict) or found.get("app") != "slipwright":
        return None
    return {**found, "address": address}


def look(
    *addresses: str | None,
    instance: str,
    client: httpx.Client,
    own: Callable[[], str | None] = own_address,
    scan: Callable[[list[str], set[int], set[str]], list[str]] = listening,
) -> list[dict[str, object]]:
    """Every Slipwright on the networks ``addresses`` point at. This one is among them,
    marked ``this_one``, when it is found at an address of its own: in Docker that is the
    only way it learns the address another computer would use."""
    networks, ports = targets(*addresses, own=own())
    found: dict[str, dict[str, object]] = {}
    for address in scan(networks, ports, set()):
        peer = hello(address, client)
        if peer is None:
            continue
        if peer.get("instance") == instance:
            peer["this_one"] = True
        # one installation seen through two of its doors is one card
        found.setdefault(str(peer.get("instance")), peer)
    return sorted(found.values(), key=lambda p: str(p.get("name", "")).lower())


def machine_name() -> str:
    """What this installation is called on another's screen. A container's host name is
    its id, which says nothing to anybody; ``SLIPWRIGHT_NAME`` is asked first for that."""
    import os

    named = os.environ.get("SLIPWRIGHT_NAME", "").strip()
    if named:
        return named[:60]
    host = socket.gethostname()
    if len(host) == 12 and all(c in "0123456789abcdef" for c in host):
        return "Slipwright"
    return host[:60] or "Slipwright"


__all__ = ["DEFAULT_PORT", "hello", "listening", "look", "machine_name", "own_address", "targets"]
