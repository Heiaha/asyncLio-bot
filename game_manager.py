import asyncio
from lichess import Lichess
from game import Game
from matchmaker import Matchmaker
from collections import deque


class GameManager:
    def __init__(self, li: Lichess, config: dict):
        self.li: Lichess = li
        self.config: dict = config
        self.pending_games = []
        self.ongoing_games: dict[str, asyncio.Task] = {}
        self.challenges: deque[str] = deque()
        self.matchmaker: Matchmaker = Matchmaker(li, config)
        self.event: asyncio.Event = asyncio.Event()

    async def run(self):
        while True:
            try:
                await asyncio.wait_for(
                    self.event.wait(), timeout=self.config["matchmaking"]["delay"]
                )
            except asyncio.TimeoutError:
                if self._under_concurrency():
                    await self.matchmaker.challenge()

            self.event.clear()

            self.ongoing_games = {
                game_id: task
                for game_id, task in self.ongoing_games.items()
                if not task.done()
            }

            while self.challenges and self._under_concurrency():
                challenge_id = self.challenges.popleft()
                if await self.li.accept_challenge(challenge_id):
                    self.pending_games.append(challenge_id)

    def _should_accept(self, event: dict) -> bool:
        allowed_variants = self.config["challenge"]["variants"]
        allowed_tcs = self.config["challenge"]["time_controls"]
        min_increment = self.config["challenge"].get("min_increment", 0)
        max_increment = self.config["challenge"].get("max_increment", 180)
        min_initial = self.config["challenge"].get("min_initial", 0)
        max_initial = self.config["challenge"].get("max_initial", 315360000)

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

    def _under_concurrency(self):
        return len(self.ongoing_games) + len(self.pending_games) < self.config["challenge"]["concurrency"]

    async def on_challenge(self, event):
        challenge_id = event["challenge"]["id"]
        challenger_name = event["challenge"]["challenger"]["name"]

        if challenger_name == self.li.username:
            return

        print(f"ID: {challenge_id}\tChallenger: {challenger_name}")
        if self._should_accept(event):
            self.challenges.append(event["challenge"]["id"])
            self.event.set()
        else:
            await self.li.decline_challenge(challenge_id)

    def on_challenge_cancel(self, event: dict):
        self.challenges.remove(event["challenge"]["id"])

    def on_game_start(self, event: dict):
        game_id = event["game"]["id"]
        game = Game(self.li, self.config, event)
        if game_id in self.pending_games:
            self.pending_games.remove(game_id)
        self.ongoing_games[game_id] = asyncio.create_task(game.play())
        self.event.set()

    def on_game_finish(self):
        self.event.set()
