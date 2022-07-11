import json
import logging

import backoff
import chess
import httpx

from typing import Callable
from config import CONFIG


def _is_final_error(e: Exception) -> bool:
    return isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500


# If backoff.on_exception times out, it will return the exception here.
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

        self.client = httpx.AsyncClient(headers=self.headers)

        self.username: str | None = None

    @classmethod
    async def create(cls):
        li = cls()
        li.username = (await li.get_account())["username"]
        return li

    async def watch_control_stream(self):
        while True:
            try:
                async with self.client.stream(
                    "GET", "https://lichess.org/api/stream/event", timeout=None
                ) as resp:
                    async for line in resp.aiter_lines():
                        line = line.encode("utf-8")
                        if line == b"\n":
                            event = {"type": "ping"}
                        else:
                            event = json.loads(line)
                        yield event
                return
            except Exception as e:
                logging.error(e)

    async def watch_game_stream(self, game_id):
        while True:
            try:
                async with self.client.stream(
                    "GET",
                    f"https://lichess.org/api/bot/game/stream/{game_id}",
                    timeout=None,
                ) as resp:
                    async for line in resp.aiter_lines():
                        line = line.encode("utf-8")
                        if line == b"\n":
                            event = {"type": "ping"}
                        else:
                            event = json.loads(line)
                        yield event
                return
            except Exception as e:
                logging.error(e)

    async def get_account(self):
        response = await self.client.get("https://lichess.org/api/account")
        return response.json()

    async def accept_challenge(self, challenge_id: str) -> bool:
        try:
            response = await self.client.post(
                f"https://lichess.org/api/challenge/{challenge_id}/accept"
            )
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            logging.error(e)
            return False

    async def decline_challenge(self, challenge_id: str) -> bool:
        try:
            response = await self.client.post(
                f"https://lichess.org/api/challenge/{challenge_id}/decline"
            )
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            logging.error(e)
            return False

    async def create_challenge(self, challenge: dict) -> bool:
        try:
            response = await self.client.post(
                f"https://lichess.org/api/challenge/{challenge['opponent']}",
                data={
                    "rated": str(CONFIG["matchmaking"]["rated"]).lower(),
                    "clock.limit": challenge["tc_seconds"],
                    "clock.increment": challenge["tc_increment"],
                    "color": "random",
                    "variant": "standard",
                },
                timeout=30,
            )
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            logging.error(e)
            return False

    async def get_online_bots(self):
        try:
            async with self.client.stream(
                "GET", "https://lichess.org/api/bot/online"
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    bot = json.loads(line)
                    yield bot
        except httpx.HTTPStatusError as e:
            logging.error(e)

    async def get_ongoing_games(self):
        try:
            response = await self.client.get("https://lichess.org/api/account/playing")
            for game_info in response.json()["nowPlaying"]:
                yield game_info
        except httpx.HTTPStatusError as e:
            logging.error(e)

    @_catch_status_code
    @backoff.on_exception(
        backoff.expo, httpx.HTTPError, max_time=300, giveup=_is_final_error
    )
    async def make_move(self, game_id: str, move: chess.Move):
        response = await self.client.post(
            f"https://lichess.org/api/bot/game/{game_id}/move/{move.uci()}",
        )
        response.raise_for_status()

    @_catch_status_code
    @backoff.on_exception(
        backoff.expo, httpx.HTTPError, max_time=300, giveup=_is_final_error
    )
    async def abort_game(self, game_id: str):
        response = await self.client.post(
            f"https://lichess.org/api/bot/game/{game_id}/abort"
        )
        response.raise_for_status()
