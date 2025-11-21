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

logger = logging.getLogger(__name__)


class Lichess:
    ATTEMPTS = 10

    async def __aenter__(self):
        headers = {
            "Authorization": f"Bearer {CONFIG['token']}",
        }
        user_info = httpx.get("https://lichess.org/api/account", headers=headers).json()
        headers["User-Agent"] = f"asyncLio-bot user:{user_info['username']}"

        self.username: str = user_info["username"]
        self.title: str = user_info.get("title", "")
        self.client: httpx.AsyncClient = httpx.AsyncClient(
            base_url="https://lichess.org",
            headers=headers,
            timeout=60,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
        logger.debug("Client closed")

    @property
    def me(self):
        return f"{self.title} {self.username}"

    async def post(self, endpoint: str, **kwargs) -> None:
        for attempt in range(self.ATTEMPTS):
            try:
                response = await self.client.post(endpoint, **kwargs)
            except httpx.RequestError:
                logger.warning("Connection error on %s", endpoint)
            except Exception as e:
                logger.exception("Error %s on %s", e, endpoint)
                return
            else:
                if response.is_success:
                    return

                if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                    await asyncio.sleep(60)
                elif response.is_client_error:
                    logger.warning(
                        "Error %d (%s) on %s.",
                        response.status_code,
                        httpx.codes.get_reason_phrase(response.status_code),
                        endpoint,
                    )
                    return

            await asyncio.sleep(2**attempt + random.random())

        logger.warning("Giving up requests on %s", endpoint)

    async def stream(self, endpoint: str):
        attempt = 0
        while True:
            try:
                async with self.client.stream("GET", endpoint) as response:
                    if response.is_success:
                        async for line in response.aiter_lines():
                            if line.strip():
                                event = json.loads(line)
                                logger.debug("Event %s: %s", endpoint, event)
                            else:
                                event = {"type": "ping"}
                            yield event
                        return
            except Exception as e:
                logger.exception("Error %s on event stream %s", e, endpoint)
            else:
                if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                    await asyncio.sleep(60)  # Wait an extra minute before retrying
                elif response.is_client_error:
                    logger.warning(
                        "Error %d (%s) on %s.",
                        response.status_code,
                        httpx.codes.get_reason_phrase(response.status_code),
                        endpoint,
                    )
                    return

            await asyncio.sleep(2**attempt + random.random())
            attempt += 1

    async def event_stream(self) -> AsyncIterator[dict]:
        while True:  # in case the event stream expires
            async for event in self.stream("/api/stream/event"):
                yield event

    async def game_stream(self, game_id: str) -> AsyncIterator[dict]:
        async for event in self.stream(f"/api/bot/game/stream/{game_id}"):
            yield event

    async def get_online_bots(self) -> AsyncIterator[dict]:
        async for event in self.stream("/api/bot/online"):
            yield event

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
        await self.post(
            f"/api/challenge/{opponent}",
            data={
                "rated": str(CONFIG["matchmaking"]["rated"]).lower(),
                "clock.limit": initial_time,
                "clock.increment": increment,
                "variant": CONFIG["matchmaking"]["variant"],
                "color": "random",
            },
        )
