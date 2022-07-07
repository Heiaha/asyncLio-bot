import random

from config import CONFIG
from lichess import Lichess


def classify_tc(tc_seconds, tc_increment=0):
    duration = tc_seconds + 40 * tc_increment
    if duration < 179:
        return "bullet"

    if duration < 479:
        return "blitz"

    if duration < 1499:
        return "rapid"

    return "classical"


class Bot:
    def __init__(self, info):
        self.name = info["username"]

        self._ratings = {}
        self._num_games = {}
        for tc_name in ("bullet", "blitz", "rapid", "classical"):
            self._ratings[tc_name] = info["perfs"][tc_name]["rating"]
            self._num_games[tc_name] = info["perfs"][tc_name]["games"]

    @property
    def total_games(self):
        return sum(self._num_games.values())

    def num_games(self, tc_name):
        return self._num_games[tc_name]

    def rating(self, tc_name):
        return self._ratings[tc_name]

    def __eq__(self, other):
        return self.name == other.name


class Matchmaker:
    def __init__(self, li: Lichess):
        self.li: Lichess = li

    async def challenge(self):

        bots = [Bot(info) async for info in self.li.get_online_bots()]
        me = next(bot for bot in bots if bot.name == self.li.username)
        random.shuffle(bots)

        tc_seconds = random.choice(CONFIG["matchmaking"]["initial_times"])
        tc_increment = random.choice(CONFIG["matchmaking"]["increments"])
        tc_name = classify_tc(tc_seconds, tc_increment)

        for bot in bots:

            if bot == me:
                continue

            if (
                abs(bot.rating(tc_name) - me.rating(tc_name))
                > CONFIG["matchmaking"]["max_rating_diff"]
            ):
                continue

            if bot.total_games < CONFIG["matchmaking"]["min_games"]:
                continue

            print(
                f"Challenging {bot.name} to a {tc_name} game with time control of {tc_seconds} seconds."
            )

            challenge = {
                "opponent": bot.name,
                "tc_seconds": tc_seconds,
                "tc_increment": tc_increment,
            }
            await self.li.create_challenge(challenge)
            return
