"""Network status adapter.

NetworkManager owns connections. This module only reports state and, when
nmcli is available, can list Wi-Fi networks or request a connection. It does
not implement its own wireless stack.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
from dataclasses import dataclass


@dataclass(slots=True)
class NetworkStatus:
    connected: bool
    interface: str | None
    ssid: str | None
    addresses: list[str]
    hostname: str
    nmcli_available: bool
    detail: str


class NetworkAdapter:
    def __init__(self, hostname: str = "frame") -> None:
        self.hostname = hostname

    def status(self) -> NetworkStatus:
        addresses = _local_addresses()
        connected = any(not addr.startswith("127.") for addr in addresses)
        ssid = None
        interface = None
        detail = "os-managed"
        nmcli = shutil.which("nmcli")
        if nmcli:
            try:
                completed = subprocess.run(
                    [nmcli, "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                detail = completed.stdout.strip() or detail
                for line in completed.stdout.splitlines():
                    parts = line.split(":")
                    if len(parts) >= 4 and parts[1] == "wifi" and parts[2] == "connected":
                        interface = parts[0]
                        ssid = parts[3] or None
                        connected = True
                        break
            except (OSError, subprocess.TimeoutExpired):
                detail = "nmcli unavailable"
        return NetworkStatus(
            connected=connected,
            interface=interface,
            ssid=ssid,
            addresses=addresses,
            hostname=self.hostname,
            nmcli_available=bool(nmcli),
            detail=detail[:500],
        )

    def wifi_networks(self) -> list[str]:
        nmcli = shutil.which("nmcli")
        if not nmcli:
            return []
        try:
            completed = subprocess.run(
                [nmcli, "-t", "-f", "SSID,SIGNAL", "device", "wifi", "list", "--rescan", "no"],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        seen: list[str] = []
        for line in completed.stdout.splitlines():
            ssid = line.split(":")[0].strip()
            if ssid and ssid not in seen:
                seen.append(ssid)
        return seen[:30]

    def connect_wifi(self, ssid: str, password: str) -> tuple[bool, str]:
        """Ask NetworkManager to store and activate a connection.

        The password is passed as a process argument and is not logged.
        """
        nmcli = shutil.which("nmcli")
        if not nmcli:
            return False, "NetworkManager (nmcli) is not available on this machine"
        if not ssid or any(char in ssid for char in "\n\r"):
            return False, "SSID is invalid"
        try:
            completed = subprocess.run(
                [nmcli, "device", "wifi", "connect", ssid, "password", password],
                check=False,
                capture_output=True,
                text=True,
                timeout=45,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"NetworkManager request failed: {exc.__class__.__name__}"
        message = (completed.stdout or completed.stderr or "").strip()
        # Never echo the password back even if nmcli repeats the command line.
        message = message.replace(password, "[redacted]") if password else message
        return completed.returncode == 0, message[:400] or "no output from NetworkManager"


def _local_addresses() -> list[str]:
    addresses: list[str] = []
    try:
        host = socket.gethostname()
        for item in socket.getaddrinfo(host, None):
            addr = item[4][0]
            if addr not in addresses and ":" not in addr:
                addresses.append(addr)
    except OSError:
        pass
    if not addresses:
        addresses.append("127.0.0.1")
    return addresses
