"""Start the private local WorkLifeBalance dashboard."""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from betteroption.settings import Settings  # noqa: E402
from betteroption.runtime import print_virtual_environment_warning  # noqa: E402


def main() -> int:
    load_dotenv()
    print_virtual_environment_warning()
    settings = Settings()
    print(f"WorkLifeBalance is ready at http://{settings.web_host}:{settings.web_port}")
    print("This v0.6.3 preview includes the private profile conversation.")
    print("Press Ctrl+C to stop it.")
    uvicorn.run(
        "betteroption.web.app:create_app",
        factory=True,
        host=settings.web_host,
        port=settings.web_port,
        reload=settings.debug,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
