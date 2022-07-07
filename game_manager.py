import asyncio
from collections import deque

from config import CONFIG
from game import Game
from lichess import Lichess
from matchmaker import Matchmaker


class GameManager:
    def __init__(self, li: Lichess):
        self.li: Lichess = li
        self.matchmaker: Matchmaker = Matchmaker(self.li)
        self.current_games: int = 0
        self.challenge_queue: deque[str] = deque()
        self.event: asyncio.Event = asyncio.Event()

    async def run(self):
        while True:
            try:
                await asyncio.wait_for(
                    self.event.wait(), timeout=CONFIG["matchmaking"]["timeout"]
                )
            except asyncio.TimeoutError:
                if self._is_under_concurrency():
                    await self.matchmaker.challenge()

            self.event.clear()

            while (
                self.current_games < CONFIG["challenge"]["concurrency"]
                and self.challenge_queue
            ):
                await self.li.accept_challenge(self.challenge_queue.popleft())

    def on_game_start(self, event):
        self.event.set()
        game = Game(self.li, event["game"]["id"])
        asyncio.create_task(game.play())
        self.current_games += 1
        print(25 * "-" + f" Current Processes: {self.current_games} " + 25 * "-")

    def on_game_finish(self):
        self.event.set()
        self.current_games -= 1
        print(25 * "-" + f" Current Processes: {self.current_games} " + 25 * "-")

    async def on_challenge(self, event):
        challenge_id = event["challenge"]["id"]
        challenger_name = event["challenge"]["challenger"]["name"]
        if challenger_name == self.li.username:
            return

        print(f"ID: {challenge_id}\tChallenger: {challenger_name}")
        if self._should_accept(event):
            self.challenge_queue.append(challenge_id)
            self.event.set()
        else:
            await self.li.decline_challenge(challenge_id)

    def _is_under_concurrency(self) -> bool:
        return self.current_games < CONFIG["challenge"]["concurrency"]

    @staticmethod
    def _should_accept(event: dict) -> bool:
        allowed_variants = CONFIG["challenge"]["variants"]
        allowed_tcs = CONFIG["challenge"]["time_controls"]
        min_increment = CONFIG["challenge"].get("min_increment", 0)
        max_increment = CONFIG["challenge"].get("max_increment", 180)
        min_initial = CONFIG["challenge"].get("min_initial", 0)
        max_initial = CONFIG["challenge"].get("max_initial", 315360000)

        increment = event["challenge"]["timeControl"].get("increment")
        initial = event["challenge"]["timeControl"].get("limit")
        variant = event["challenge"]["variant"]["key"]
        tc = event["challenge"]["speed"]

        if variant not in allowed_variants:
            return False

        if tc not in allowed_tcs:
            return False

        if not (min_initial <= initial <= max_initial):
            return False

        if not (min_increment <= increment <= max_increment):
            return False

        return True
