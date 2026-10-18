"""``auto-short web``: run the web app with uvicorn (requires the ``[web]`` extra)."""

from __future__ import annotations

import logging

import uvicorn

from ..config import Config
from .app import create_app
from .auth import password_from_env

log = logging.getLogger("auto_short")


def serve(config: Config, *, host: str, port: int) -> None:
    """Blocks until Ctrl-C / SIGTERM. Raises :class:`auth.AuthError` before binding when the password env var
    is missing or the secret file is unusable."""
    app = create_app(config, password_from_env())
    log.info("web: listening on http://%s:%d (workspace %s, output %s)", host, port, config.workspace.dir,
             config.render.output_dir)
    runner = app.state.runner

    class _Server(uvicorn.Server):
        def handle_exit(self, sig, frame) -> None:
            runner.begin_stop()  # FIX-runner-stop: before the lanes can take another job while the server winds down
            super().handle_exit(sig, frame)

    _Server(uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False,
                           timeout_graceful_shutdown=5)).run()
