import json
from typing import AsyncIterator

import backoff
import chess
import httpx

from config import CONFIG


class Lichess:
    def __init__(self) -> None:

        headers = {
            "Authorization": f"Bearer {CONFIG['token']}",
        }

        user = httpx.get("https://lichess.org/api/account", headers=headers).json()

        self.username = user["username"]
        self.title = user.get("title", "")

        headers["User-Agent"] = f"Hermod user:{self.username}"

        self.client = httpx.AsyncClient(
            base_url="https://lichess.org",
            headers=headers,
        )

    @backoff.on_exception(backoff.expo, httpx.HTTPStatusError)
    async def get(self, endpoint: str, **kwargs) -> httpx.Response:
        response = await self.client.get(endpoint, **kwargs)
        if response.status_code < 500:
            return response
        else:
            response.raise_for_status()

    @backoff.on_exception(backoff.expo, httpx.HTTPStatusError, max_time=300)
    async def post(self, endpoint: str, **kwargs) -> httpx.Response:
        response = await self.client.post(endpoint, **kwargs)
        if response.status_code < 500:
            return response
        else:
            response.raise_for_status()

    async def watch_control_stream(self) -> AsyncIterator[dict]:
        while True:
            try:
                async with self.client.stream(
                    "GET", "/api/stream/event", timeout=None
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.strip():
                            event = json.loads(line)
                        else:
                            event = {"type": "ping"}
                        yield event
                return
            except httpx.HTTPStatusError:
                pass

    async def watch_game_stream(self, game_id: str) -> AsyncIterator[dict]:
        while True:
            try:
                async with self.client.stream(
                    "GET",
                    f"/api/bot/game/stream/{game_id}",
                    timeout=None,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.strip():
                            event = json.loads(line)
                        else:
                            event = {"type": "ping"}
                        yield event
                return
            except httpx.HTTPStatusError:
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
            return

    async def accept_challenge(self, challenge_id: str) -> bool:
        response = await self.post(f"/api/challenge/{challenge_id}/accept")
        if response.status_code == 200:
            return True
        else:
            return False

    async def decline_challenge(self, challenge_id: str) -> bool:
        response = await self.post(f"/api/challenge/{challenge_id}/decline")
        if response.status_code == 200:
            return True
        else:
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
            return ""

    async def cancel_challenge(self, challenge_id: str) -> bool:
        response = await self.post(f"/api/challenge/{challenge_id}/cancel")
        if response.status_code == 200:
            return True
        else:
            return False

    async def abort_game(self, game_id: str) -> bool:
        response = await self.post(f"/api/bot/game/{game_id}/abort")
        if response.status_code == 200:
            return True
        else:
            return False

    async def resign_game(self, game_id: str) -> bool:
        response = await self.post(f"/api/bot/game/{game_id}/resign")
        if response.status_code == 200:
            return True
        else:
            return False

    async def get_open_challenges(self) -> dict:
        response = await self.get("/api/challenge")
        if response.status_code == 200:
            return response.json()
        else:
            return {}

    async def get_ongoing_games(self) -> list[str]:
        response = await self.get("/api/account/playing")
        if response.status_code == 200:
            return [game_info["gameId"] for game_info in response.json()["nowPlaying"]]
        else:
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
            return False

    async def upgrade_account(self) -> bool:
        response = await self.post("/api/bot/account/upgrade")
        if response.status_code == 200:
            return True
        else:
            return False
