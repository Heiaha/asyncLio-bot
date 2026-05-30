import asyncio
import json
import logging
import random
import time
from typing import AsyncIterator

import chess
import httpx

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
        account = Account.model_validate_json(
            httpx.get("https://lichess.org/api/account", headers=headers).content
        )
        headers["User-Agent"] = f"asyncLio-bot user:{account.username}"

        self.username: str = account.username
        self.title: str = account.title
        self.client: httpx.AsyncClient = httpx.AsyncClient(
            base_url="https://lichess.org",
            headers=headers,
            timeout=60,
        )
        self.challenge_timeout: float = 0.0
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
        logger.debug("Client closed")

    @property
    def me(self):
        return f"{self.title} {self.username}".strip()

    @staticmethod
    def is_fatal_client_error(response: httpx.Response) -> bool:
        # 429 is retried after a longer sleep; other 4xxs mean the request
        # itself is wrong and retrying won't help.
        return (
            response.is_client_error
            and response.status_code != httpx.codes.TOO_MANY_REQUESTS
        )

    @staticmethod
    def log_client_error(response: httpx.Response, endpoint: str) -> None:
        logger.warning(
            "Error %d (%s) on %s.",
            response.status_code,
            httpx.codes.get_reason_phrase(response.status_code),
            endpoint,
        )

    @staticmethod
    def rate_limit_seconds(response: httpx.Response) -> float | None:
        # A 429 carrying {"ratelimit": {"seconds": N}} means a quota is spent (e.g. the
        # 100/day bot-vs-bot cap). Return N so we can wait it out; None otherwise.
        if response.status_code != httpx.codes.TOO_MANY_REQUESTS:
            return None
        if "json" not in response.headers.get("content-type", ""):
            return None
        return RateLimit.model_validate_json(response.content).seconds

    @staticmethod
    async def backoff(response: httpx.Response | None, attempt: int) -> None:
        if response is not None and response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            await asyncio.sleep(60)
        await asyncio.sleep(2**attempt + random.random())

    async def post(
        self, endpoint: str, retry: bool = True, **kwargs
    ) -> httpx.Response | None:
        for attempt in range(self.ATTEMPTS):
            response = None
            try:
                response = await self.client.post(endpoint, **kwargs)
            except httpx.RequestError:
                logger.warning("Connection error on %s", endpoint)
            except Exception as e:
                logger.exception("Error %s on %s", e, endpoint)
                return None
            else:
                if response.is_success:
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
                async with self.client.stream("GET", endpoint) as response:
                    if response.is_success:
                        async for line in response.aiter_lines():
                            yield line
                        return
            except httpx.RequestError as e:
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
                "clock.limit": initial_time,
                "clock.increment": increment,
                "variant": CONFIG.matchmaking.variant.value,
                "color": "random",
            },
            retry=False,
        )
        if response is not None and (
            seconds := self.rate_limit_seconds(response)
        ) is not None:
            self.challenge_timeout = time.monotonic() + seconds
            logger.info("Rate limited; pausing matchmaking for %.0fs", seconds)
