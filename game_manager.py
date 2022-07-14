import asyncio
import logging
from collections import deque

from config import CONFIG
from game import Game
from lichess import Lichess
from matchmaker import Matchmaker


class GameManager:
    def __init__(self, li: Lichess):
        self.li: Lichess = li
        self.matchmaker: Matchmaker = Matchmaker(self.li)
        self.current_games: dict[str, (Game, asyncio.Task)] = {}
        self.challenge_queue: deque[str] = deque()
        self.event: asyncio.Event = asyncio.Event()

    async def run(self):
        while True:
            try:
                await asyncio.wait_for(
                    self.event.wait(), timeout=CONFIG["matchmaking"]["timeout"]
                )
            except asyncio.TimeoutError:
                if (
                    self._is_under_concurrency_limit()
                    and CONFIG["matchmaking"]["enabled"]
                ):
                    await self.matchmaker.challenge()
                continue

            self.event.clear()

            while self._is_under_concurrency_limit() and self.challenge_queue:
                await self.li.accept_challenge(self.challenge_queue.popleft())

    async def on_game_start(self, event: dict):
        game_id = event["game"]["id"]
        opponent = event["game"]["opponent"]["username"]

        # If this is an extremely late acceptance of a challenge we issued earlier
        # that would bring us over our concurrency limit, abort it.
        if not self._is_under_concurrency_limit():
            await self.li.abort_game(game_id)
            return

        game = Game(self.li, game_id)
        task = asyncio.create_task(game.play())

        self.current_games[game_id] = game, task
        self.event.set()
        logging.info(f"Game {game_id} starting against {opponent}.")
        logging.info(f"Current Processes: {len(self.current_games)}")

    async def on_game_finish(self, event: dict):
        if (game_id := event["game"]["id"]) in self.current_games:
            game, task = self.current_games.pop(game_id)
            await task
        self.event.set()
        logging.info(f"Current Processes: {len(self.current_games)}")

    async def on_challenge(self, event: dict):
        challenge_id = event["challenge"]["id"]
        challenger_name = event["challenge"]["challenger"]["name"]
        if challenger_name == self.li.username:
            return

        logging.info(f"ID: {challenge_id}\tChallenger: {challenger_name}")
        if self._should_accept(event):
            self.challenge_queue.append(challenge_id)
            self.event.set()
        else:
            await self.li.decline_challenge(challenge_id)

    def on_challenge_cancelled(self, event: dict):
        challenge_id = event["challenge"]["id"]
        if challenge_id in self.challenge_queue:
            self.challenge_queue.remove(challenge_id)

    def _is_under_concurrency_limit(self) -> bool:
        return len(self.current_games) < CONFIG["concurrency"]

    @staticmethod
    def _should_accept(event: dict) -> bool:

        allowed_variants = CONFIG["challenge"]["variants"]
        allowed_tcs = CONFIG["challenge"]["time_controls"]
        min_increment = CONFIG["challenge"].get("min_increment", 0)
        max_increment = CONFIG["challenge"].get("max_increment", 180)
        min_initial = CONFIG["challenge"].get("min_initial", 0)
        max_initial = CONFIG["challenge"].get("max_initial", 315360000)

        enabled = CONFIG["challenge"]["enabled"]
        if not enabled:
            return False

        variant = event["challenge"]["variant"]["key"]
        if variant not in allowed_variants:
            return False

        increment = event["challenge"]["timeControl"].get("increment")
        initial = event["challenge"]["timeControl"].get("limit")
        speed = event["challenge"]["speed"]

        if speed not in allowed_tcs:
            return False

        if not (min_initial <= initial <= max_initial):
            return False

        if not (min_increment <= increment <= max_increment):
            return False

        return True

    def clean_games(self):
        # Sometimes the lichess game loop seems to close without the event loop sending a "gameFinish" event
        # but still having closed the game stream. This function will take case of those cases.
        self.current_games = {
            game_id: (game, task)
            for game_id, (game, task) in self.current_games.items()
            if not game.is_game_over()
        }
