"""Pure policy model for the v3 WSS primary/fallback design.

This is an executable contract, NOT the runtime Rust implementation.
No production network requests are made.
"""
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit


class Failure(Enum):
    DNS = "dns"
    CONNECT_REFUSED = "connect_refused"
    UNREACHABLE = "unreachable"
    CONNECT_TIMEOUT = "connect_timeout"
    CERTIFICATE = "certificate"
    TLS = "tls"
    REDIRECT = "redirect"
    AUTH = "auth"
    PROTOCOL = "protocol"
    APPLICATION = "application"


ELIGIBLE = frozenset({
    Failure.DNS, Failure.CONNECT_REFUSED, Failure.UNREACHABLE,
    Failure.CONNECT_TIMEOUT,
})


@dataclass(frozen=True)
class Candidate:
    url: str
    role: str
    side: str


def _origin(value: str):
    p = urlsplit(value)
    if (p.scheme != "https" or not p.hostname or p.username or p.password
            or p.path not in ("", "/") or p.query or p.fragment):
        raise ValueError("expected HTTPS origin")
    try:
        port = p.port
    except ValueError as exc:
        raise ValueError("invalid origin port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("invalid origin port")
    return p


def _host(value: str) -> str:
    p = urlsplit("//" + value)
    if not p.hostname or p.username or p.password or p.path or p.query or p.fragment:
        raise ValueError("invalid endpoint host")
    return p.hostname.lower().rstrip(".")


def candidates(endpoint: str, own_id: str, primary: str, fallback: str,
               role: str = "id", *, enabled: bool = True,
               verified_own_relay: bool = False,
               explicit_websocket_port: bool = False):
    """Return a pair only for an unqualified, verified own endpoint.

    Caller must separately check that the endpoint's port/role was classified
    by the RustDesk protocol, and must not pass peer-supplied relay addresses.
    """
    if not enabled or explicit_websocket_port or role not in ("id", "relay"):
        return ()
    if endpoint.startswith(("ws://", "wss://")) or "://" in endpoint:
        return ()
    if role == "relay" and not verified_own_relay:
        return ()
    try:
        endpoint_host = _host(endpoint)
        own_host = _host(own_id)
        a, b = _origin(primary), _origin(fallback)
    except ValueError:
        return ()
    if endpoint_host != own_host or endpoint_host != a.hostname.lower().rstrip("."):
        return ()
    if a.netloc.lower() == b.netloc.lower():
        return ()
    path = "/ws/id" if role == "id" else "/ws/relay"
    return (
        Candidate("wss://" + a.netloc + path, role, "primary"),
        Candidate("wss://" + b.netloc + path, role, "fallback"),
    )


def should_try_fallback(failure: Failure) -> bool:
    return failure in ELIGIBLE
