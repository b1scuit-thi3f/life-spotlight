"""Wi-Fi setup payloads and the network snapshot on the status page."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(slots=True)
class NetworkStatus:
    connected: bool
    interface: str | None
    ssid: str | None
    addresses: list[str]
    hostname: str
    nmcliAvailable: bool
    detail: str


class NetworkState(BaseModel):
    connected: bool
    ssid: str | None
    addresses: list[str]
    nmcliAvailable: bool


class WifiUpdate(BaseModel):
    ssid: str = Field(min_length=1, max_length=64)
    password: str = Field(default="", max_length=128)


class WifiNetworks(BaseModel):
    networks: list[str]
    nmcli: bool


class WifiConnectResult(BaseModel):
    ok: bool
    message: str
