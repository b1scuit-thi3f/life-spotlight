"""Process arguments and logging. Saved settings live in photo_frame.core.settings."""

from photo_frame.config.logging import configureLogging
from photo_frame.config.runtime import RuntimeConfig, runtimeFromArgs

__all__ = [
    "RuntimeConfig",
    "configureLogging",
    "runtimeFromArgs",
]
