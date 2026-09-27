"""Process configuration.

Only host, port, data directory, hostname, and log level are process
arguments. Every other setting lives in SQLite and is edited from the admin UI.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


@dataclass(slots=True)
class RuntimeConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    data_dir: Path = Path("./data")
    hostname: str = "frame"
    log_level: str = "INFO"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "photo_frame.sqlite"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="photo-frame",
        description="Local photo frame for a single Immich album.",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Address to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind (default: 8080)")
    parser.add_argument(
        "--data-dir",
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
        default="INFO",
        choices=LOG_LEVELS,
        help="Log level (default: INFO)",
    )
    return parser


def runtime_from_args(argv: list[str] | None = None) -> RuntimeConfig:
    args = build_parser().parse_args(argv)
    hostname = str(args.hostname).strip() or "frame"
    if any(char in hostname for char in " \t\n\r./"):
        raise SystemExit("hostname must be a single DNS label")
    if not 1 <= args.port <= 65535:
        raise SystemExit("port must be between 1 and 65535")
    return RuntimeConfig(
        host=str(args.host).strip() or "0.0.0.0",
        port=int(args.port),
        data_dir=Path(args.data_dir).expanduser(),
        hostname=hostname,
        log_level=str(args.log_level).upper(),
    )
