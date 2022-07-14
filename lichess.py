import json
import logging

import backoff
import chess
import httpx

from typing import Callable, AsyncGenerator
from config import CONFIG


def _is_final_error(e: Exception) -> bool:
    return isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500


# If backoff.on_exception times out or gives up,
# it will return the exception here in this decorator.
# Catch if it is a httpx.HTTPStatusError
def _catch_status_code(f: Callable):
    async def wrapper(*args, **kwargs):
        try:
            await f(*args, **kwargs)
            return True
        except httpx.HTTPStatusError:
            return False

    return wrapper


class Lichess:
    def __init__(self):
        self.token = CONFIG["token"]
        self.headers = {
            "Authorization": f"Bearer {self.token}",
        }

        self.client = httpx.AsyncClient(
            base_url="https://lichess.org", headers=self.headers
        )

        self.user: dict | None = None

    @classmethod
    async def create(cls):
        li = cls()
        li.user = await li.get_account()
        return li

    @property
    def username(self):
        return self.user["username"]

    @property
    def title(self):
        return self.user.get("title")

    async def watch_control_stream(self) -> AsyncGenerator[dict, dict]:
        while True:
            try:
                async with self.client.stream(
                    "GET", "/api/stream/event", timeout=None
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line.strip():
                            event = json.loads(line)
                        else:
                            event = {"type": "ping"}
                        yield event
                return
            except Exception as e:
                logging.error("Error while watching control stream.")
                logging.error(e)

    async def watch_game_stream(self, game_id) -> AsyncGenerator[dict, dict]:
        while True:
            try:
                async with self.client.stream(
                    "GET",
                    f"/api/bot/game/stream/{game_id}",
                    timeout=None,
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line.strip():
                            event = json.loads(line)
                        else:
                            event = {"type": "ping"}
                        yield event
                return
            except Exception as e:
                if game_id not in await self.get_ongoing_games():
                    return
                logging.error("Error while watching game stream.")
                logging.error(e)

    async def get_account(self):
        response = await self.client.get("/api/account")
        return response.json()

    async def accept_challenge(self, challenge_id: str) -> bool:
        try:
            response = await self.client.post(f"/api/challenge/{challenge_id}/accept")
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError:
            return False

    async def decline_challenge(self, challenge_id: str) -> bool:
        try:
            response = await self.client.post(f"/api/challenge/{challenge_id}/decline")
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError:
            return False

    async def create_challenge(
        self, opponent: str, initial_time: int, increment: int = 0
    ) -> str | None:
        try:
            response = await self.client.post(
                f"/api/challenge/{opponent}",
                data={
                    "rated": str(CONFIG["matchmaking"]["rated"]).lower(),
                    "clock.limit": initial_time,
                    "clock.increment": increment,
                    "variant": CONFIG["matchmaking"]["variant"],
                    "color": "random",
                },
                timeout=20,
            )
            response.raise_for_status()
            return response.json()["challenge"]["id"]
        except httpx.HTTPStatusError:
            logging.warning(f"Could not create challenge against {opponent}.")

    async def cancel_challenge(self, challenge_id: str) -> bool:
        try:
            response = await self.client.post(f"/api/challenge/{challenge_id}/cancel")
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError:
            return False

    async def abort_game(self, game_id: str) -> bool:
        try:
            response = await self.client.post(f"/api/bot/game/{game_id}/abort")
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError:
            return False

    async def get_open_challenges(self) -> dict:
        try:
            response = await self.client.get("/api/challenge")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logging.error(f"Could not fetch open challenges.")
            logging.error(e)

    async def get_online_bots(self) -> AsyncGenerator[dict, dict]:
        try:
            async with self.client.stream("GET", "/api/bot/online") as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    bot = json.loads(line)
                    yield bot
        except httpx.HTTPStatusError as e:
            logging.error("Could not fetch online bots.")
            logging.error(e)

    async def get_ongoing_games(self) -> list[str]:
        try:
            response = await self.client.get("https://lichess.org/api/account/playing")
            response.raise_for_status()
            return [game_info["gameId"] for game_info in response.json()["nowPlaying"]]
        except httpx.HTTPStatusError as e:
            logging.error("Could not fetch ongoing games.")
            logging.error(e)
            return []

    @_catch_status_code
    @backoff.on_exception(
        backoff.expo, httpx.HTTPError, max_time=300, giveup=_is_final_error
    )
    async def make_move(self, game_id: str, move: chess.Move):
        response = await self.client.post(
            f"/api/bot/game/{game_id}/move/{move.uci()}",
        )
        response.raise_for_status()

    async def upgrade_account(self) -> bool:
        try:
            response = await self.client.post("/api/bot/account/upgrade")
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError:
            return False
