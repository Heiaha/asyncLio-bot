import asyncio
import random
import logging

from config import CONFIG
from lichess import Lichess
from enums import PerfType, Variant


class Bot:
    def __init__(self, info):
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
    def total_games(self):
        return sum(self._num_games.values())

    def num_games(self, perf_type):
        return self._num_games[perf_type]

    def rating(self, perf_type):
        return self._ratings[perf_type]

    def __eq__(self, other):
        return self.name == other.name


class Matchmaker:
    def __init__(self, li: Lichess):
        self.li: Lichess = li

    def _should_challenge(self, bot: Bot, me: Bot, perf_type: PerfType) -> bool:
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

    async def challenge(self):
        bots = [Bot(info) async for info in self.li.get_online_bots()]
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
                    f"Challenging {bot.name} to a {perf_type.value} game with time control of {tc_seconds} seconds."
                )

                challenge = {
                    "opponent": bot.name,
                    "tc_seconds": tc_seconds,
                    "tc_increment": tc_increment,
                }

                # Send challenge request.
                challenge_id = await self.li.create_challenge(challenge)

                # Wait 20 seconds and try to cancel the challenge in case it hasn't been responded to.
                await asyncio.sleep(20)
                if challenge_id:
                    await self.li.cancel_challenge(challenge_id)
                return
