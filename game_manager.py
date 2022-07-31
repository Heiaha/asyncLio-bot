import asyncio
from collections import deque
from typing import NoReturn

from loguru import logger

from config import CONFIG
from enums import Event, DeclineReason
from game import Game
from lichess import Lichess
from matchmaker import Matchmaker


class GameManager:
    def __init__(self, li: Lichess) -> None:
        self.li: Lichess = li
        self.matchmaker: Matchmaker = Matchmaker(self.li)
        self.current_games: dict[str, Game] = {}
        self.challenge_queue: deque[str] = deque()
        self.event: asyncio.Event = asyncio.Event()

    async def event_loop(self) -> NoReturn:
        asyncio.create_task(self.challenge_loop())
        async for event in self.li.watch_event_stream():
            event_type = Event(event["type"])

            if event_type == Event.PING:
                self.clean_games()

            elif event_type == Event.GAME_START:
                await self.on_game_start(event)

            elif event_type == Event.GAME_FINISH:
                await self.on_game_finish(event)

            elif event_type == Event.CHALLENGE:
                await self.on_challenge(event)

            elif event_type == Event.CHALLENGE_CANCELED:
                self.on_challenge_cancelled(event)

    async def challenge_loop(self) -> NoReturn:
        while True:
            try:
                await asyncio.wait_for(
                    self.event.wait(),
                    timeout=CONFIG["matchmaking"]["timeout"] * 60
                    if CONFIG["matchmaking"]["enabled"]
                    else None,
                )
            except asyncio.TimeoutError:
                if self.is_under_concurrency_limit():
                    await self.matchmaker.challenge()
                continue

            self.event.clear()

            while self.is_under_concurrency_limit() and self.challenge_queue:
                await self.li.accept_challenge(self.challenge_queue.popleft())

    async def on_ping(self):
        self.clean_games()

    async def on_game_start(self, event: dict) -> None:
        game_id = event["game"]["id"]
        opponent = event["game"]["opponent"]["username"]

        # If this is an extremely late acceptance of a challenge we issued earlier
        # that would bring us over our concurrency limit, abort it.
        if not self.is_under_concurrency_limit():
            await self.li.abort_game(game_id)
            return

        game = Game(self.li, event)
        game.play()  # non-blocking task creation
        self.current_games[game_id] = game

        self.event.set()
        logger.info(f"Game {game_id} starting against {opponent}.")
        logger.info(f"Current Processes: {len(self.current_games)}.")

    async def on_game_finish(self, event: dict) -> None:
        if (game_id := event["game"]["id"]) in self.current_games:
            game = self.current_games.pop(game_id)

            # await task here to return and output any potential errors, but don't let it close the event loop
            try:
                await game.loop_task
            except Exception as e:
                logger.error(e)

        self.event.set()
        logger.info(f"Current Processes: {len(self.current_games)}.")

    async def on_challenge(self, event: dict) -> None:
        challenge_id = event["challenge"]["id"]
        challenger_name = event["challenge"]["challenger"]["name"]
        if challenger_name == self.li.username:
            return

        logger.info(f"{challenge_id} -- Challenger: {challenger_name}.")
        if decline_reason := DeclineReason.from_event(event):
            logger.info(
                f"Declining challenge from {challenger_name} for reason: {decline_reason}."
            )
            await self.li.decline_challenge(challenge_id, reason=decline_reason)
        else:
            self.challenge_queue.append(challenge_id)
            self.event.set()

    def on_challenge_cancelled(self, event: dict) -> None:
        challenge_id = event["challenge"]["id"]
        challenger_name = event["challenge"]["challenger"]["name"]
        if challenge_id in self.challenge_queue:
            logger.info(f"{challenge_id} -- Challenge from {challenger_name} removed.")
            self.challenge_queue.remove(challenge_id)

    def is_under_concurrency_limit(self) -> bool:
        return len(self.current_games) < CONFIG["concurrency"]

    def clean_games(self) -> None:
        # Sometimes the lichess game loop seems to close without the event loop sending a "gameFinish" event
        # but still having closed the game stream. This function will take case of those cases.
        self.current_games = {
            game_id: game
            for game_id, game in self.current_games.items()
            if not game.is_game_over()
        }
