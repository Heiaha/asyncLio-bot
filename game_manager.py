import asyncio
import logging
import time
from collections import deque
from typing import NoReturn

from config import CONFIG
from enums import Event, DeclineReason, Variant
from game import Game
from lichess import Lichess
from matchmaker import Matchmaker

logger = logging.getLogger(__name__)


class GameManager:
    def __init__(self, li: Lichess) -> None:
        self.li: Lichess = li
        self.matchmaker: Matchmaker = Matchmaker(li)
        self.current_games: dict[str, Game] = {}
        self.challenge_queue: deque[str] = deque()
        self.last_event_time: float = time.monotonic()

    async def watch_event_stream(self) -> NoReturn:
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
        # Sometimes the lichess game loop seems to close without the event loop sending a "gameFinish" event
        # but still having closed the game stream. This will take care of those cases.
        self.current_games = {
            game_id: game
            for game_id, game in self.current_games.items()
            if not game.loop_task.done()
        }

        logger.debug(f"Active tasks: {len(asyncio.all_tasks())}")

        if self.is_under_concurrency_limit() and self.challenge_queue:
            await self.li.accept_challenge(self.challenge_queue.popleft())
            return

        if self.should_create_challenge():
            self.last_event_time = time.monotonic()
            await self.matchmaker.challenge()

    async def on_game_start(self, event: dict) -> None:
        self.last_event_time = time.monotonic()
        game_id = event["game"]["id"]

        if game_id in self.current_games:
            return

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
            logger.info(f"{game} finished.")
            await game.loop_task

        logger.info(
            f"Games: {len(self.current_games)}. Challenges: {len(self.challenge_queue)}."
        )

        if self.is_under_concurrency_limit() and self.challenge_queue:
            await self.li.accept_challenge(self.challenge_queue.popleft())

    async def on_challenge(self, event: dict) -> None:
        self.last_event_time = time.monotonic()
        challenge_id = event["challenge"]["id"]

        if challenge_id in self.challenge_queue:
            return

        if challenger_info := event["challenge"]["challenger"]:
            challenger_name = challenger_info["name"]
        else:
            challenger_name = "Anonymous"

        if challenger_name == self.li.username:
            return

        logger.info(f"{challenge_id} -- Challenger: {challenger_name}.")
        if decline_reason := self.check_decline_reason(event):
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
        logger.info(f"{challenge_id} -- Challenge canceled.")
        if challenge_id in self.challenge_queue:
            self.challenge_queue.remove(challenge_id)
        logger.info(
            f"Games: {len(self.current_games)}. Challenges: {len(self.challenge_queue)}."
        )

    def is_under_concurrency_limit(self) -> bool:
        return len(self.current_games) < CONFIG["concurrency"]

    def should_create_challenge(self) -> bool:
        if not CONFIG["matchmaking"]["enabled"]:
            return False

        if len(self.current_games) > 0:
            return False

        return (
            time.monotonic() - self.last_event_time
            >= max(1, CONFIG["matchmaking"]["timeout"]) * 60
        )

    @staticmethod
    def check_decline_reason(event: dict) -> DeclineReason | None:
        challenge_config = CONFIG["challenge"]
        if not challenge_config["enabled"]:
            return DeclineReason.GENERIC

        allowed_modes = challenge_config["modes"]
        allowed_opponents = challenge_config["opponents"]
        allowed_variants = challenge_config["variants"]
        allowed_tcs = challenge_config["time_controls"]
        min_increment = challenge_config.get("min_increment", 0)
        max_increment = challenge_config.get("max_increment", 180)
        min_initial = challenge_config.get("min_initial", 0)
        max_initial = challenge_config.get("max_initial", 315360000)
        max_bot_rating_diff = challenge_config["max_rating_diffs"].get("bot", 4000)
        max_human_rating_diff = challenge_config["max_rating_diffs"].get("human", 4000)

        challenge_info = event["challenge"]
        is_rated = challenge_info["rated"]
        if is_rated and "rated" not in allowed_modes:
            return DeclineReason.CASUAL

        if not is_rated and "casual" not in allowed_modes:
            return DeclineReason.RATED

        variant = challenge_info["variant"]["key"]
        if variant not in allowed_variants:
            return (
                DeclineReason.STANDARD
                if allowed_variants == [Variant.STANDARD.value]
                else DeclineReason.VARIANT
            )

        if challenger_info := challenge_info["challenger"]:
            is_bot = challenger_info["title"] == "BOT"
            their_rating = challenger_info.get("rating")
        else:
            is_bot = False
            their_rating = None

        if my_info := challenge_info["destUser"]:
            my_rating = my_info.get("rating")
        else:
            my_rating = None

        if is_bot and "bot" not in allowed_opponents:
            return DeclineReason.NO_BOT

        if not is_bot and "human" not in allowed_opponents:
            return DeclineReason.ONLY_BOT

        increment = challenge_info["timeControl"].get("increment", 0)
        initial = challenge_info["timeControl"].get("limit", 0)
        speed = challenge_info["speed"]
        if speed not in allowed_tcs:
            return DeclineReason.TIME_CONTROL

        if initial < min_initial or increment < min_increment:
            return DeclineReason.TOO_FAST

        if initial > max_initial or increment > max_increment:
            return DeclineReason.TOO_SLOW

        if is_rated and my_rating is not None and their_rating is not None:
            rating_diff = abs(my_rating - their_rating)
            max_rating_diff = max_bot_rating_diff if is_bot else max_human_rating_diff
            if rating_diff > max_rating_diff:
                return DeclineReason.GENERIC

        return None
