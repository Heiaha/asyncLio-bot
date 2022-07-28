import json
from typing import AsyncIterator

import backoff
import chess
import httpx
from loguru import logger

from config import CONFIG


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
            base_url="https://lichess.org", headers=headers,
        )

    @backoff.on_predicate(
        backoff.expo, lambda response: response.status_code >= 500, max_time=300
    )
    async def get(self, endpoint: str, **kwargs) -> httpx.Response:
        response = await self.client.get(endpoint, **kwargs)
        logger.debug(
            f"Endpoint: {endpoint}, kwargs: {kwargs}, code: {response.status_code}, text: {response.text}"
        )
        return response

    @backoff.on_predicate(
        backoff.expo, lambda response: response.status_code >= 500, max_time=300
    )
    async def post(self, endpoint: str, **kwargs) -> httpx.Response:
        response = await self.client.post(endpoint, **kwargs)
        logger.debug(
            f"Endpoint: {endpoint}, kwargs: {kwargs}, code: {response.status_code}, text: {response.text}"
        )
        return response

    async def watch_event_stream(self) -> AsyncIterator[dict]:
        while True:
            try:
                async with self.client.stream(
                    "GET", "/api/stream/event", timeout=None
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.strip():
                            event = json.loads(line)
                            logger.debug(f"Event: {event}")
                        else:
                            event = {"type": "ping"}
                        yield event
                return
            except Exception as e:
                logger.error(e)
                pass

    async def watch_game_stream(self, game_id: str) -> AsyncIterator[dict]:
        while True:
            try:
                async with self.client.stream(
                    "GET", f"/api/bot/game/stream/{game_id}", timeout=None,
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
                logger.error(e)
                if game_id not in await self.get_ongoing_games():
                    return

    async def get_online_bots(self) -> AsyncIterator[dict]:
        try:
            async with self.client.stream("GET", "/api/bot/online") as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    bot = json.loads(line)
                    yield bot
        except httpx.HTTPStatusError as e:
            logger.error(e)

    async def accept_challenge(self, challenge_id: str) -> bool:
        response = await self.post(f"/api/challenge/{challenge_id}/accept")
        if response.status_code == 200:
            return True
        else:
            logger.error(f"Status code {response.status_code}: {response.text}")
            return False

    async def decline_challenge(self, challenge_id: str) -> bool:
        response = await self.post(f"/api/challenge/{challenge_id}/decline")
        if response.status_code == 200:
            return True
        else:
            logger.error(f"Status code {response.status_code}: {response.text}")
            return False

    async def create_challenge(
        self, opponent: str, initial_time: int, increment: int = 0
    ) -> str:

        response = await self.post(
            f"/api/challenge/{opponent}",
            data={
                "rated": str(CONFIG["matchmaking"]["rated"]).lower(),
                "clock.limit": initial_time,
                "clock.increment": increment,
                "variant": CONFIG["matchmaking"]["variant"],
                "color": "random",
            },
        )
        if response.status_code == 200:
            return response.json()["challenge"]["id"]
        else:
            logger.error(f"Status code {response.status_code}: {response.text}")
            return ""

    async def cancel_challenge(self, challenge_id: str) -> bool:
        response = await self.post(f"/api/challenge/{challenge_id}/cancel")
        if response.status_code == 200:
            return True
        else:
            logger.error(f"Status code {response.status_code}: {response.text}")
            return False

    async def abort_game(self, game_id: str) -> bool:
        response = await self.post(f"/api/bot/game/{game_id}/abort")
        if response.status_code == 200:
            return True
        else:
            logger.error(f"Status code {response.status_code}: {response.text}")
            return False

    async def resign_game(self, game_id: str) -> bool:
        response = await self.post(f"/api/bot/game/{game_id}/resign")
        if response.status_code == 200:
            return True
        else:
            logger.error(f"Status code {response.status_code}: {response.text}")
            return False

    async def get_open_challenges(self) -> dict:
        response = await self.get("/api/challenge")
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Status code {response.status_code}: {response.text}")
            return {}

    async def get_ongoing_games(self) -> list[str]:
        response = await self.get("/api/account/playing")
        if response.status_code == 200:
            return [game_info["gameId"] for game_info in response.json()["nowPlaying"]]
        else:
            logger.error(f"Status code {response.status_code}: {response.text}")
            return []

    async def make_move(
        self, game_id: str, move: chess.Move, offer_draw: bool = False
    ) -> bool:
        response = await self.post(
            f"/api/bot/game/{game_id}/move/{move.uci()}",
            params={"offeringDraw": str(offer_draw).lower()},
        )
        if response.status_code == 200:
            return True
        else:
            logger.error(f"Status code {response.status_code}: {response.text}")
            return False

    async def upgrade_account(self) -> bool:
        response = await self.post("/api/bot/account/upgrade")
        if response.status_code == 200:
            return True
        else:
            logger.error(f"Status code {response.status_code}: {response.text}")
            return False
