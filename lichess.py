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
        logger.debug("Client closed.")

    @property
    def me(self):
        return f"{self.title} {self.username}"

    async def post(self, endpoint: str, **kwargs) -> None:
        start_time = time.monotonic()
        delay = 1

        while time.monotonic() - start_time < 600:
            try:
                response = await self.client.post(endpoint, **kwargs)
                response.raise_for_status()
                return  # Success, exit the function
            except httpx.RequestError:
                logger.warning(f"Connection error on {endpoint}.")
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                logger.warning(
                    f"Error {status_code} ({httpx.codes.get_reason_phrase(status_code)}) on {endpoint}."
                )
                if status_code == httpx.codes.TOO_MANY_REQUESTS:
                    delay += 60
                elif httpx.codes.is_client_error(status_code):
                    return  # Exit on client errors (4xx, except 429)
                #  Otherwise sleep at end of loop
            except Exception:
                logger.exception(f"Error on {endpoint}.")
                return  # Unrecoverable error, exit the function

            await asyncio.sleep(delay)
            delay = min(60, 2 * delay) + random.uniform(0, 1)
        logger.warning(f"Giving up requests on {endpoint}.")

    async def stream(self, endpoint: str):
        while True:
            delay = random.uniform(0, 2)
            try:
                async with self.client.stream("GET", endpoint) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.strip():
                            event = json.loads(line)
                            logger.debug(f"Event {endpoint}: {event}")
                        else:
                            event = {"type": "ping"}
                        yield event
                    return
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                logger.warning(
                    f"Error {status_code} ({httpx.codes.get_reason_phrase(status_code)}) on {endpoint}."
                )
                if status_code == httpx.codes.TOO_MANY_REQUESTS:
                    delay += 60
                elif httpx.codes.is_client_error(status_code):
                    return  # Exit on client errors (4xx, except 429)
                #  Otherwise sleep at end of loop
            except Exception:
                logger.exception(f"Error in event stream {endpoint}.")

            await asyncio.sleep(delay)

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
