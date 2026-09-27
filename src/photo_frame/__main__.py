"""Entry point for ``python -m photo_frame`` and the console script."""

from __future__ import annotations

import uvicorn

from photo_frame.config import configure_logging, runtime_from_args


def main(argv: list[str] | None = None) -> None:
    runtime = runtime_from_args(argv)
    configure_logging(runtime.log_level)
    uvicorn.run(
        "photo_frame.app:create_app",
        factory=True,
        host=runtime.host,
        port=runtime.port,
        log_level=runtime.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
