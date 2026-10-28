"""/canfar/firefly/ensure — POST starts or joins a Firefly launch, GET reports it."""

from __future__ import annotations

import asyncio
import json

import tornado
from jupyter_server.base.handlers import APIHandler

from ..firefly_session import FireflyLauncher


class EnsureFireflyHandler(APIHandler):
    def initialize(self, launcher: FireflyLauncher) -> None:
        self.launcher = launcher

    @tornado.web.authenticated
    def get(self) -> None:
        self.finish(json.dumps(self.launcher.status()))

    @tornado.web.authenticated
    async def post(self) -> None:
        loop = asyncio.get_running_loop()
        state = await loop.run_in_executor(None, self.launcher.start)
        self.finish(json.dumps(state))
