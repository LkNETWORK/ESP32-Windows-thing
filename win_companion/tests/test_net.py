from __future__ import annotations

from companion.net import AddressEntry, rank_addresses


def test_ethernet_lan_beats_vpn() -> None:
    entries = [
        AddressEntry("OpenVPN Data Channel Offload", "10.8.0.2"),
        AddressEntry("Ethernet", "192.168.31.198"),
        AddressEntry("Loopback Pseudo-Interface 1", "127.0.0.1", True),
        AddressEntry("Ethernet", "169.254.10.20"),
    ]
    ranked = rank_addresses(entries)
    assert ranked[0].address == "192.168.31.198"
    addresses = [item.address for item in ranked]
    assert "127.0.0.1" not in addresses
    assert "169.254.10.20" not in addresses
    assert "10.8.0.2" in addresses
    assert ranked[-1].address == "10.8.0.2"


def test_duplicate_addresses_are_removed() -> None:
    entries = [
        AddressEntry("Ethernet", "192.168.1.20"),
        AddressEntry("Wi-Fi", "192.168.1.20"),
    ]
    assert len(rank_addresses(entries)) == 1


def test_down_interface_is_ignored() -> None:
    entries = [AddressEntry("Ethernet", "192.168.1.20", is_up=False)]
    assert rank_addresses(entries) == []


def test_wifi_is_preferred() -> None:
    entries = [
        AddressEntry("Ethernet", "192.168.1.20"),
        AddressEntry("Wi-Fi", "192.168.1.21"),
    ]
    assert rank_addresses(entries)[0].interface == "Wi-Fi"
