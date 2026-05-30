import asyncio
import logging
import time
from collections import deque
from typing import NoReturn

from config import CONFIG
from enums import ChallengeMode, ChallengeOpponent, DeclineReason, Event, Variant
from game import Game
from lichess import Lichess
from matchmaker import Matchmaker
from models import (
    ChallengeCanceledEvent,
    ChallengeEvent,
    GameFinishEvent,
    GameStartEvent,
)

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
            match event.type:
                case Event.PING:
                    await self.on_ping()
                case Event.GAME_START:
                    await self.on_game_start(event)
                case Event.GAME_FINISH:
                    await self.on_game_finish(event)
                case Event.CHALLENGE:
                    await self.on_challenge(event)
                case Event.CHALLENGE_CANCELED:
                    self.on_challenge_canceled(event)

    async def on_ping(self) -> None:
        # Sometimes the lichess game loop seems to close without the event loop sending a "gameFinish" event
        # but still having closed the game stream. This will take care of those cases.
        self.current_games = {
            game_id: game
            for game_id, game in self.current_games.items()
            if not game.loop_task.done()
        }

        logger.debug("Active tasks: %d", len(asyncio.all_tasks()))

        if self.is_under_concurrency_limit() and self.challenge_queue:
            await self.li.accept_challenge(self.challenge_queue.popleft())
            return

        if self.should_create_challenge():
            self.last_event_time = time.monotonic()
            await self.matchmaker.challenge()

    async def on_game_start(self, event: GameStartEvent) -> None:
        self.last_event_time = time.monotonic()
        game_id = event.game.id

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
            "Games: %d, Challenges: %d",
            len(self.current_games),
            len(self.challenge_queue),
        )
        logger.info("%s starting", game)

    async def on_game_finish(self, event: GameFinishEvent) -> None:
        self.last_event_time = time.monotonic()
        if (game_id := event.game.id) in self.current_games:
            game = self.current_games.pop(game_id)
            logger.info("%s finished", game)
            await game.loop_task

        logger.info(
            "Games: %d, Challenges: %d",
            len(self.current_games),
            len(self.challenge_queue),
        )

        if self.is_under_concurrency_limit() and self.challenge_queue:
            await self.li.accept_challenge(self.challenge_queue.popleft())

    async def on_challenge(self, event: ChallengeEvent) -> None:
        challenge = event.challenge

        if challenge.id in self.challenge_queue:
            return

        challenger_name = (
            challenge.challenger.name if challenge.challenger else "Anonymous"
        )

        if challenger_name == self.li.username:
            return

        logger.info("%s -- Challenger: %s", challenge.id, challenger_name)
        if decline_reason := self.check_decline_reason(event):
            logger.info(
                "%s -- Declining challenge from %s for reason: %s",
                challenge.id,
                challenger_name,
                decline_reason,
            )
            await self.li.decline_challenge(challenge.id, reason=decline_reason)
            return

        if self.is_under_concurrency_limit():
            await self.li.accept_challenge(challenge.id)
            return

        self.challenge_queue.append(challenge.id)
        logger.info(
            "Games: %d, Challenges: %d",
            len(self.current_games),
            len(self.challenge_queue),
        )

    def on_challenge_canceled(self, event: ChallengeCanceledEvent) -> None:
        self.last_event_time = time.monotonic()
        challenge_id = event.challenge.id
        logger.info("%s -- Challenge canceled.", challenge_id)
        if challenge_id in self.challenge_queue:
            self.challenge_queue.remove(challenge_id)
        logger.info(
            "Games: %d, Challenges: %d",
            len(self.current_games),
            len(self.challenge_queue),
        )

    def is_under_concurrency_limit(self) -> bool:
        return len(self.current_games) < CONFIG.concurrency

    def should_create_challenge(self) -> bool:
        if not CONFIG.matchmaking.enabled:
            return False

        if time.monotonic() < self.li.challenge_timeout:
            return False

        if len(self.current_games) > 0:
            return False

        return (
            time.monotonic() - self.last_event_time
            >= max(1, CONFIG.matchmaking.timeout) * 60
        )

    @staticmethod
    def check_decline_reason(event: ChallengeEvent) -> DeclineReason | None:
        cfg = CONFIG.challenge
        if not cfg.enabled:
            return DeclineReason.GENERIC

        challenge = event.challenge
        if challenge.rated and ChallengeMode.RATED not in cfg.modes:
            return DeclineReason.CASUAL

        if not challenge.rated and ChallengeMode.CASUAL not in cfg.modes:
            return DeclineReason.RATED

        if challenge.variant not in cfg.variants:
            return (
                DeclineReason.STANDARD
                if cfg.variants == [Variant.STANDARD]
                else DeclineReason.VARIANT
            )

        if challenger := challenge.challenger:
            is_bot = challenger.title == "BOT"
            their_rating = challenger.rating
        else:
            is_bot = False
            their_rating = None

        my_rating = challenge.dest_user.rating if challenge.dest_user else None

        if is_bot and ChallengeOpponent.BOT not in cfg.opponents:
            return DeclineReason.NO_BOT

        if not is_bot and ChallengeOpponent.HUMAN not in cfg.opponents:
            return DeclineReason.ONLY_BOT

        if challenge.speed not in cfg.time_controls:
            return DeclineReason.TIME_CONTROL

        initial = challenge.time_control.limit
        increment = challenge.time_control.increment
        if initial < cfg.min_initial or increment < cfg.min_increment:
            return DeclineReason.TOO_FAST

        if initial > cfg.max_initial or increment > cfg.max_increment:
            return DeclineReason.TOO_SLOW

        if challenge.rated and my_rating is not None and their_rating is not None:
            rating_diff = abs(my_rating - their_rating)
            max_rating_diff = (
                cfg.max_rating_diffs.bot if is_bot else cfg.max_rating_diffs.human
            )
            if rating_diff > max_rating_diff:
                return DeclineReason.GENERIC

        return None
