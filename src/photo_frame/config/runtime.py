"""Process configuration.

Only host, port, data directory, hostname, and log level are process
arguments. Every other setting lives in SQLite and is edited from the admin UI.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

@dataclass(slots=True)
class RuntimeConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    dataDir: Path = field(default_factory=lambda: Path("./data"))
    hostname: str = "frame"
    logLevel: str = "INFO"

    @property
    def databasePath(self) -> Path:
        return self.dataDir / "photo_frame.sqlite"

    @property
    def cacheDir(self) -> Path:
        return self.dataDir / "cache"

    @property
    def tmpDir(self) -> Path:
        return self.dataDir / "tmp"

    def ensureDirs(self) -> None:
        self.dataDir.mkdir(parents=True, exist_ok=True)
        self.cacheDir.mkdir(parents=True, exist_ok=True)
        self.tmpDir.mkdir(parents=True, exist_ok=True)


def buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="photo-frame",
        description="Local photo frame for a single Immich album.",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Address to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind (default: 8080)")
    parser.add_argument(
        "--data-dir",
        dest="dataDir",
        default="./data",
        help="Directory for the SQLite database and media cache (default: ./data)",
    )
    parser.add_argument(
        "--hostname",
        default="frame",
        help="mDNS hostname advertised as <hostname>.local (default: frame)",
    )
    parser.add_argument(
        "--log-level",
        dest="logLevel",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Log level (default: INFO)",
    )
    return parser


def runtimeFromArgs(argv: list[str] | None = None) -> RuntimeConfig:
    args = buildParser().parse_args(argv)
    hostname = str(args.hostname).strip() or "frame"
    if any(char in hostname for char in " \t\n\r./"):
        raise SystemExit("hostname must be a single DNS label")
    if not 1 <= args.port <= 65535:
        raise SystemExit("port must be between 1 and 65535")
    return RuntimeConfig(
        host=str(args.host).strip() or "0.0.0.0",
        port=int(args.port),
        dataDir=Path(args.dataDir).expanduser(),
        hostname=hostname,
        logLevel=str(args.logLevel).upper(),
    )
