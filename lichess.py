import json
import logging
from typing import AsyncIterator

import backoff
import chess
import httpx

from config import CONFIG
from enums import DeclineReason

logger = logging.getLogger(__name__)


class Lichess:
    def __init__(self) -> None:
        headers = {
            "Authorization": f"Bearer {CONFIG['token']}",
        }
        user_info = httpx.get("https://lichess.org/api/account", headers=headers).json()
        self.username = user_info["username"]
        self.title = user_info.get("title", "")
        headers["User-Agent"] = f"asyncLio-bot user:{self.username}"
        self.client = httpx.AsyncClient(
            base_url="https://lichess.org",
            headers=headers,
        )

    @backoff.on_exception(
        backoff.constant,
        httpx.RequestError,  # non-HTTP status errors
        max_time=60,
        logger=logger,
        backoff_log_level=logging.WARNING,
        giveup_log_level=logging.ERROR,
        raise_on_giveup=False,
    )
    @backoff.on_predicate(
        backoff.expo,
        lambda response: response.status_code >= 500,
        max_time=300,
        logger=logger,
        backoff_log_level=logging.WARNING,
        giveup_log_level=logging.ERROR,
    )
    async def post(self, endpoint: str, **kwargs):
        return await self.client.post(endpoint, **kwargs)

    async def event_stream(self) -> AsyncIterator[dict]:
        while True:
            try:
                async with self.client.stream(
                    "GET", "/api/stream/event", timeout=20
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.strip():
                            event = json.loads(line)
                            logger.debug(f"Event: {event}")
                        else:
                            event = {"type": "ping"}
                        yield event
            except Exception as e:
                logger.warning(e)

    async def game_stream(self, game_id: str) -> AsyncIterator[dict]:
        while True:
            try:
                async with self.client.stream(
                    "GET",
                    f"/api/bot/game/stream/{game_id}",
                    timeout=20,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.strip():
                            event = json.loads(line)
                            logger.debug(f"Game event: {event}")
                        else:
                            event = {"type": "ping"}
                        yield event
                return
            except Exception as e:
                logger.warning(e)

    async def get_online_bots(self) -> AsyncIterator[dict]:
        try:
            async with self.client.stream("GET", "/api/bot/online") as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    bot = json.loads(line)
                    yield bot
        except Exception as e:
            logger.warning(e)

    async def accept_challenge(self, challenge_id: str) -> None:
        await self.post(f"/api/challenge/{challenge_id}/accept")

    async def decline_challenge(
        self, challenge_id: str, *, reason: DeclineReason = DeclineReason.GENERIC
    ) -> None:
        await self.post(
            f"/api/challenge/{challenge_id}/decline", data={"reason": reason.value}
        )

    async def cancel_challenge(self, challenge_id: str) -> None:
        await self.post(f"/api/challenge/{challenge_id}/cancel")

    async def abort_game(self, game_id: str) -> None:
        await self.post(f"/api/bot/game/{game_id}/abort")

    async def resign_game(self, game_id: str) -> None:
        await self.post(f"/api/bot/game/{game_id}/resign")

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
