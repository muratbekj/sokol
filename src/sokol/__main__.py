"""Entrypoint: `python -m sokol` or the `sokol` script."""

from __future__ import annotations

import logging

from .bot import build_application
from .config import load_config


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = load_config()
    app = build_application(config)
    logging.getLogger(__name__).info(
        "sokol bot starting (model=%s, allowed users=%s)",
        config.chat_model,
        sorted(config.allowed_user_ids),
    )
    app.run_polling()


if __name__ == "__main__":
    main()
