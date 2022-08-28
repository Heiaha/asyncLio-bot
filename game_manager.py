import logging
import time
from collections import deque
from typing import NoReturn

from config import CONFIG
from enums import Event, DeclineReason
from game import Game
from lichess import Lichess
from matchmaker import Matchmaker

logger = logging.getLogger(__name__)


class GameManager:
    def __init__(self, li: Lichess) -> None:
        self.li: Lichess = li
        self.current_games: dict[str, Game] = {}
        self.challenge_queue: deque[str] = deque()
        self.last_event_time = time.monotonic()

    async def watch_event_loop(self) -> NoReturn:
        async for event in self.li.event_stream():
            event_type = Event(event["type"])

            if event_type == Event.PING:
                await self.on_ping()

            elif event_type == Event.GAME_START:
                await self.on_game_start(event)

            elif event_type == Event.GAME_FINISH:
                await self.on_game_finish(event)

            elif event_type == Event.CHALLENGE:
                await self.on_challenge(event)

            elif event_type == Event.CHALLENGE_CANCELED:
                self.on_challenge_canceled(event)

    async def on_ping(self) -> None:
        self.clean_games()
        if (
            CONFIG["matchmaking"]["enabled"]
            and len(self.current_games) == 0
            and time.monotonic()
            >= self.last_event_time + CONFIG["matchmaking"]["timeout"] * 60
        ):
            self.last_event_time = time.monotonic()
            await Matchmaker(self.li).challenge()

    async def on_game_start(self, event: dict) -> None:
        self.last_event_time = time.monotonic()
        game_id = event["game"]["id"]

        # If this is an extremely late acceptance of a challenge we issued earlier
        # that would bring us over our concurrency limit, abort it.
        if not self.is_under_concurrency_limit():
            await self.li.abort_game(game_id)
            return

        game = Game(self.li, event)
        game.start()  # non-blocking task creation
        self.current_games[game_id] = game

        logger.info(
            f"Games: {len(self.current_games)}. Challenges: {len(self.challenge_queue)}."
        )
        logger.info(f"{game} starting.")

    async def on_game_finish(self, event: dict) -> None:
        self.last_event_time = time.monotonic()
        if (game_id := event["game"]["id"]) in self.current_games:
            game = self.current_games.pop(game_id)

            # await task here to return and output any potential errors, but don't let it close the event loop
            try:
                await game.loop_task
            except Exception as e:
                logger.error(e)

            logger.info(f"{game} finished.")

        logger.info(
            f"Games: {len(self.current_games)}. Challenges: {len(self.challenge_queue)}."
        )

        if self.is_under_concurrency_limit() and self.challenge_queue:
            await self.li.accept_challenge(self.challenge_queue.popleft())

    async def on_challenge(self, event: dict) -> None:
        self.last_event_time = time.monotonic()
        challenge_id = event["challenge"]["id"]
        challenger_name = event["challenge"]["challenger"]["name"]
        if challenger_name == self.li.username:
            return

        logger.info(f"{challenge_id} -- Challenger: {challenger_name}.")
        if decline_reason := DeclineReason.from_event(event):
            logger.info(
                f"{challenge_id} -- Declining challenge from {challenger_name} for reason: {decline_reason}."
            )
            await self.li.decline_challenge(challenge_id, reason=decline_reason)
            return

        if self.is_under_concurrency_limit():
            await self.li.accept_challenge(challenge_id)
            return

        self.challenge_queue.append(challenge_id)
        logger.info(
            f"Games: {len(self.current_games)}. Challenges: {len(self.challenge_queue)}."
        )

    def on_challenge_canceled(self, event: dict) -> None:
        self.last_event_time = time.monotonic()
        challenge_id = event["challenge"]["id"]
        challenger_name = event["challenge"]["challenger"]["name"]
        logger.info(f"{challenge_id} -- Challenge cancelled from: {challenger_name}.")
        if challenge_id in self.challenge_queue:
            self.challenge_queue.remove(challenge_id)
        logger.info(
            f"Games: {len(self.current_games)}. Challenges: {len(self.challenge_queue)}."
        )

    def is_under_concurrency_limit(self) -> bool:
        return len(self.current_games) < CONFIG["concurrency"]

    def clean_games(self) -> None:
        # Sometimes the lichess game loop seems to close without the event loop sending a "gameFinish" event
        # but still having closed the game stream. This function will take case of those cases.
        self.current_games = {
            game_id: game
            for game_id, game in self.current_games.items()
            if not game.is_game_over
        }
