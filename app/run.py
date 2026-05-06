from __future__ import annotations

import argparse

import uvicorn

from app.core.config import get_env_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DC Bot FastAPI app.")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload mode.")
    args = parser.parse_args()

    env = get_env_settings()
    uvicorn.run(
        "app.main:app",
        host=env.host,
        port=env.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
