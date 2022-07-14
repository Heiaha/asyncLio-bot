import logging
import random
from typing import Any

from config import CONFIG
from enums import PerfType, Variant
from lichess import Lichess


class Bot:
    def __init__(self, info) -> None:
        self.name = info["username"]

        self._ratings = {}
        self._num_games = {}
        for perf_type in PerfType:
            self._ratings[perf_type] = (
                info["perfs"].get(perf_type.value, {}).get("rating", 1500)
            )
            self._num_games[perf_type] = (
                info["perfs"].get(perf_type.value, {}).get("games", 0)
            )

    @property
    def total_games(self) -> int:
        return sum(self._num_games.values())

    def num_games(self, perf_type) -> int:
        return self._num_games[perf_type]

    def rating(self, perf_type) -> int:
        return self._ratings[perf_type]

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Bot):
            return self.name == other.name
        return NotImplemented


class Matchmaker:
    def __init__(self, li: Lichess) -> None:
        self.li: Lichess = li

    @staticmethod
    def _should_challenge(bot: Bot, me: Bot, perf_type: PerfType) -> bool:
        if bot == me:
            return False
        if (
            abs(bot.rating(perf_type) - me.rating(perf_type))
            > CONFIG["matchmaking"]["max_rating_diff"]
        ):
            return False

        if bot.total_games < CONFIG["matchmaking"]["min_games"]:
            return False

        return True

    async def challenge(self) -> None:
        bots = [
            Bot(info)
            async for info in self.li.get_online_bots()
            if not info.get("disabled")
        ]
        me = next(bot for bot in bots if bot.name == self.li.username)
        random.shuffle(bots)

        variant = Variant(CONFIG["matchmaking"]["variant"])
        tc_seconds = random.choice(CONFIG["matchmaking"]["initial_times"])
        tc_increment = random.choice(CONFIG["matchmaking"]["increments"])
        if variant == Variant.STANDARD:
            perf_type = PerfType.from_standard_tc(tc_seconds, tc_increment)
        else:
            perf_type = PerfType.from_nonstandard_variant(variant)

        for bot in bots:

            if self._should_challenge(bot, me, perf_type):
                logging.info(
                    f"Challenging {bot.name} to a {perf_type.value} game with time control of {tc_seconds//60}+{tc_increment}."
                )

                # Send challenge request.
                await self.li.create_challenge(bot.name, tc_seconds, tc_increment)
                return
