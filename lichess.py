import asyncio
import json
import logging
import random
import time
from http import HTTPStatus
from typing import AsyncIterator

import aiohttp
import chess

from config import CONFIG
from enums import DeclineReason
from models import (
    Account,
    GamePing,
    GameStreamEvent,
    OnlineBot,
    PingEvent,
    RateLimit,
    StreamEvent,
    parse_event,
    parse_game_event,
)

logger = logging.getLogger(__name__)


class Lichess:
    ATTEMPTS = 5

    async def __aenter__(self):
        headers = {
            "Authorization": f"Bearer {CONFIG.token}",
        }
        async with aiohttp.ClientSession(
            headers=headers, cookie_jar=aiohttp.DummyCookieJar()
        ) as session:
            async with session.get("https://lichess.org/api/account") as response:
                account = Account.model_validate_json(await response.read())
        headers["User-Agent"] = f"asyncLio-bot user:{account.username}"

        self.username: str = account.username
        self.title: str = account.title
        self.client: aiohttp.ClientSession = aiohttp.ClientSession(
            base_url="https://lichess.org",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=60, sock_read=60),
            cookie_jar=aiohttp.DummyCookieJar(),
        )
        self.challenge_timeout: float = 0.0
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.close()
        logger.debug("Client closed")

    @property
    def me(self):
        return f"{self.title} {self.username}".strip()

    async def fetch_blocklist(self) -> set[str]:
        users = {user.lower() for user in CONFIG.blocklist.users}
        if not CONFIG.blocklist.urls:
            return users
        # Separate client: don't send the Lichess auth token to third-party URLs.
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(
            timeout=timeout, cookie_jar=aiohttp.DummyCookieJar()
        ) as client:
            for url in CONFIG.blocklist.urls:
                try:
                    async with client.get(url) as response:
                        response.raise_for_status()
                        text = await response.text()
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning("Could not fetch blocklist from %s: %s", url, e)
                    continue
                users.update(
                    line.strip().lower()
                    for line in text.splitlines()
                    if not line.startswith("#")
                )
        return users

    @staticmethod
    def is_fatal_client_error(response: aiohttp.ClientResponse) -> bool:
        # 429 is retried after a longer sleep; other 4xxs mean the request
        # itself is wrong and retrying won't help.
        return (
            400 <= response.status < 500
            and response.status != HTTPStatus.TOO_MANY_REQUESTS
        )

    @staticmethod
    def log_client_error(response: aiohttp.ClientResponse, endpoint: str) -> None:
        logger.warning(
            "Error %d (%s) on %s.",
            response.status,
            response.reason,
            endpoint,
        )

    @staticmethod
    async def rate_limit_seconds(response: aiohttp.ClientResponse) -> float | None:
        # A 429 carrying {"ratelimit": {"seconds": N}} means a quota is spent (e.g. the
        # 100/day bot-vs-bot cap). Return N so we can wait it out; None otherwise.
        if response.status != HTTPStatus.TOO_MANY_REQUESTS:
            return None
        if "json" not in response.headers.get("content-type", ""):
            return None
        return RateLimit.model_validate_json(await response.read()).seconds

    @staticmethod
    async def backoff(response: aiohttp.ClientResponse | None, attempt: int) -> None:
        if response is not None and response.status == HTTPStatus.TOO_MANY_REQUESTS:
            await asyncio.sleep(60)
        await asyncio.sleep(2**attempt + random.random())

    async def post(
        self, endpoint: str, retry: bool = True, **kwargs
    ) -> aiohttp.ClientResponse | None:
        for attempt in range(self.ATTEMPTS):
            response = None
            try:
                async with self.client.post(endpoint, **kwargs) as resp:
                    await resp.read()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                logger.warning("Connection error on %s", endpoint)
            except Exception as e:
                logger.exception("Error %s on %s", e, endpoint)
                return None
            else:
                response = resp
                if response.ok:
                    return response
                if self.is_fatal_client_error(response):
                    self.log_client_error(response, endpoint)
                    return response

            if not retry:
                return response

            await self.backoff(response, attempt)

        logger.warning("Giving up requests on %s", endpoint)
        return response

    async def iter_lines(self, endpoint: str) -> AsyncIterator[str]:
        """Stream raw lines from `endpoint`, reconnecting on transient errors.

        Yields each line (including empty keepalive lines) until the server
        closes the stream normally or returns a fatal client error.
        """
        attempt = 0
        while True:
            response = None
            try:
                async with self.client.get(endpoint) as response:
                    if response.ok:
                        async for line in response.content:
                            yield line.decode()
                        return
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(
                    "Event stream %s disconnected (%s); reconnecting", endpoint, e
                )
            except Exception:
                logger.exception("Unexpected error on event stream %s", endpoint)
            else:
                if self.is_fatal_client_error(response):
                    self.log_client_error(response, endpoint)
                    return

            await self.backoff(response, attempt)
            attempt += 1

    @staticmethod
    def parse_line(endpoint: str, line: str) -> dict | None:
        if not line.strip():
            return None
        event = json.loads(line)
        logger.debug("Event %s: %s", endpoint, event)
        return event

    async def event_stream(self) -> AsyncIterator[StreamEvent]:
        endpoint = "/api/stream/event"
        while True:  # in case the event stream expires
            async for line in self.iter_lines(endpoint):
                event = self.parse_line(endpoint, line)
                yield PingEvent() if event is None else parse_event(event)

    async def game_stream(self, game_id: str) -> AsyncIterator[GameStreamEvent]:
        endpoint = f"/api/bot/game/stream/{game_id}"
        async for line in self.iter_lines(endpoint):
            event = self.parse_line(endpoint, line)
            yield GamePing() if event is None else parse_game_event(event)

    async def get_online_bots(self) -> AsyncIterator[OnlineBot]:
        endpoint = "/api/bot/online"
        async for line in self.iter_lines(endpoint):
            if event := self.parse_line(endpoint, line):
                yield OnlineBot.model_validate(event)

    async def accept_challenge(self, challenge_id: str) -> None:
        await self.post(f"/api/challenge/{challenge_id}/accept")

    async def decline_challenge(
        self, challenge_id: str, *, reason: DeclineReason = DeclineReason.GENERIC
    ) -> None:
        await self.post(
            f"/api/challenge/{challenge_id}/decline", data={"reason": reason}
        )

    async def cancel_challenge(self, challenge_id: str) -> None:
        await self.post(f"/api/challenge/{challenge_id}/cancel")

    async def abort_game(self, game_id: str) -> None:
        await self.post(f"/api/bot/game/{game_id}/abort")

    async def resign_game(self, game_id: str) -> None:
        await self.post(f"/api/bot/game/{game_id}/resign")

    async def claim_victory(self, game_id: str) -> None:
        await self.post(f"/api/bot/game/{game_id}/claim-victory")

    async def upgrade_account(self) -> None:
        await self.post("/api/bot/account/upgrade")

    async def make_move(
        self, game_id: str, move: chess.Move, *, offer_draw: bool = False
    ) -> None:
        await self.post(
            f"/api/bot/game/{game_id}/move/{move.uci()}",
            params={"offeringDraw": str(offer_draw).lower()},
        )

    async def create_challenge(
        self, opponent: str, initial_time: int, increment: int = 0
    ) -> None:
        response = await self.post(
            f"/api/challenge/{opponent}",
            data={
                "rated": str(CONFIG.matchmaking.rated).lower(),
                "clock.limit": str(initial_time),
                "clock.increment": str(increment),
                "variant": CONFIG.matchmaking.variant,
                "color": "random",
            },
            retry=False,
        )
        if response is not None and (
            seconds := await self.rate_limit_seconds(response)
        ) is not None:
            self.challenge_timeout = time.monotonic() + seconds
            logger.info("Rate limited; pausing matchmaking for %.0fs", seconds)
