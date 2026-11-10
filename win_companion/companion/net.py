"""Pick usable LAN URLs for phone access.

The machine may have several IPv4 addresses (Ethernet, Wi-Fi, VPN, virtual
switches). Prefer physical LAN interfaces and de-prioritize VPN/virtual ones.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Iterable

import psutil

_VPN_HINTS = (
    "vpn",
    "tap",
    "tun",
    "wireguard",
    "tailscale",
    "zerotier",
    "wintun",
    "openvpn",
    "hamachi",
    "radmin",
)
_VIRTUAL_HINTS = (
    "vethernet",
    "hyper-v",
    "virtual",
    "vmware",
    "virtualbox",
    "bluetooth",
    "loopback",
)


@dataclass(frozen=True)
class AddressEntry:
    interface: str
    address: str
    is_up: bool = True


@dataclass(frozen=True)
class LanAddress:
    interface: str
    address: str
    score: int


def _is_usable_ipv4(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (
        ip.version == 4
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_unspecified
    )


def _score(interface: str, address: str) -> int:
    name = interface.lower()
    score = 0
    if any(hint in name for hint in _VPN_HINTS):
        score -= 100
    if any(hint in name for hint in _VIRTUAL_HINTS):
        score -= 20
    if any(hint in name for hint in ("wi-fi", "wifi", "wireless", "wlan")):
        score += 30
    if "ethernet" in name or name.startswith("eth"):
        score += 20

    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return score
    if ip.is_private:
        score += 5
        if address.startswith("192.168."):
            score += 20
        elif address.startswith("10."):
            score += 10
        elif address.startswith("172."):
            try:
                second = int(address.split(".")[1])
            except (IndexError, ValueError):
                second = -1
            if 16 <= second <= 31:
                score += 10
    return score


def rank_addresses(entries: Iterable[AddressEntry]) -> list[LanAddress]:
    """Rank usable addresses; pure function, easy to unit test."""

    seen: set[str] = set()
    ranked: list[LanAddress] = []
    for entry in entries:
        if not entry.is_up or entry.address in seen:
            continue
        if not _is_usable_ipv4(entry.address):
            continue
        seen.add(entry.address)
        ranked.append(
            LanAddress(
                interface=entry.interface,
                address=entry.address,
                score=_score(entry.interface, entry.address),
            )
        )
    ranked.sort(key=lambda item: (-item.score, item.address))
    return ranked


def lan_addresses() -> list[LanAddress]:
    entries: list[AddressEntry] = []
    try:
        stats = psutil.net_if_stats()
        interfaces = psutil.net_if_addrs()
    except Exception:
        return []

    for name, addresses in interfaces.items():
        stats_entry = stats.get(name)
        is_up = bool(stats_entry.isup) if stats_entry is not None else True
        for address in addresses:
            if address.family == socket.AF_INET:
                entries.append(AddressEntry(name, address.address, is_up))
    return rank_addresses(entries)


def primary_url(port: int) -> str:
    addresses = lan_addresses()
    host = addresses[0].address if addresses else "127.0.0.1"
    return f"http://{host}:{port}/"


def all_urls(port: int) -> list[tuple[str, str]]:
    """Return ``(interface, url)`` pairs, primary first."""

    return [
        (item.interface, f"http://{item.address}:{port}/")
        for item in lan_addresses()
    ]
