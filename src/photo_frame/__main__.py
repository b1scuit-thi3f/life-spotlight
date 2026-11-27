"""Entry point for ``python -m photo_frame`` and the console script."""

from __future__ import annotations

import uvicorn

from photo_frame.config import configureLogging, runtimeFromArgs


def main(argv: list[str] | None = None) -> None:
    runtime = runtimeFromArgs(argv)
    configureLogging(runtime.logLevel)
    uvicorn.run(
        "photo_frame.api.app:createApp",
        factory=True,
        host=runtime.host,
        port=runtime.port,
        log_level=runtime.logLevel.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
