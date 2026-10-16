"""POST /canfar/firefly/ensure — create/reuse Firefly and inject URL."""

from __future__ import annotations

import asyncio
import json

import tornado
from jupyter_server.base.handlers import APIHandler

from ..firefly_session import ensure_firefly


class EnsureFireflyHandler(APIHandler):
    def initialize(self, server_app=None) -> None:
        self.server_app = server_app

    @tornado.web.authenticated
    async def post(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            config = await loop.run_in_executor(
                None, lambda: ensure_firefly(self.server_app)
            )
        except Exception as exc:
            self.set_status(500)
            self.finish(json.dumps({"error": str(exc)}))
            return
        self.finish(json.dumps(config))
