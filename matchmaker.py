import logging
import random
from typing import Any

from config import CONFIG
from enums import PerfType, Variant
from lichess import Lichess
from models import OnlineBot, PerfInfo

logger = logging.getLogger(__name__)


class Bot:
    def __init__(self, info: OnlineBot) -> None:
        self.name = info.username

        self._ratings = {}
        self._num_games = {}
        for perf_type in PerfType:
            perf = info.perfs.get(perf_type, PerfInfo())
            self._ratings[perf_type] = perf.rating
            self._num_games[perf_type] = perf.games

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Bot):
            return self.name == other.name
        return NotImplemented

    def num_games(self, perf_type) -> int:
        return self._num_games[perf_type]

    def rating(self, perf_type) -> int:
        return self._ratings[perf_type]

    def should_challenge(self, other: "Bot", perf_type: PerfType):
        if other == self:
            return False
        if (
            abs(self.rating(perf_type) - other.rating(perf_type))
            > CONFIG.matchmaking.max_rating_diff
        ):
            return False

        if other.num_games(perf_type) < CONFIG.matchmaking.min_games:
            return False

        return True


class Matchmaker:
    def __init__(self, li: Lichess) -> None:
        self.li: Lichess = li

    async def challenge(self) -> None:
        bots = [
            Bot(info)
            async for info in self.li.get_online_bots()
            if not info.disabled and not info.tos_violation
        ]
        
        try:
            me = next(bot for bot in bots if bot.name == self.li.username)
        except StopIteration:
            logger.warning("Current bot is not online in matchmaker.")
            return

        random.shuffle(bots)

        variant = CONFIG.matchmaking.variant
        tc_seconds = random.choice(CONFIG.matchmaking.initial_times)
        tc_increment = random.choice(CONFIG.matchmaking.increments)
        perf_type = (
            PerfType.from_standard_tc(tc_seconds, tc_increment)
            if variant == Variant.STANDARD
            else PerfType.from_nonstandard_variant(variant)
        )

        for bot in bots:
            if me.should_challenge(bot, perf_type):
                logger.info(
                    "Challenging %s to a %s game with time control of %d+%d",
                    bot.name,
                    perf_type,
                    tc_seconds / 60,
                    tc_increment,
                )

                # Send challenge request.
                await self.li.create_challenge(bot.name, tc_seconds, tc_increment)
                return

        logger.warning("Could not find any bot to challenge.")
