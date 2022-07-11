import random
import logging

from config import CONFIG
from lichess import Lichess
from enums import Speed


class Bot:
    def __init__(self, info):
        self.name = info["username"]

        self._ratings = {}
        self._num_games = {}
        for speed in Speed:
            self._ratings[speed] = info["perfs"][speed.value]["rating"]
            self._num_games[speed] = info["perfs"][speed.value]["games"]

    @property
    def total_games(self):
        return sum(self._num_games.values())

    def num_games(self, speed):
        return self._num_games[speed]

    def rating(self, speed):
        return self._ratings[speed]

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
        speed = Speed.from_tc(tc_seconds, tc_increment)

        for bot in bots:

            if bot == me:
                continue

            if (
                abs(bot.rating(speed) - me.rating(speed))
                > CONFIG["matchmaking"]["max_rating_diff"]
            ):
                continue

            if bot.total_games < CONFIG["matchmaking"]["min_games"]:
                continue

            logging.info(
                f"Challenging {bot.name} to a {speed.value} game with time control of {tc_seconds} seconds."
            )

            challenge = {
                "opponent": bot.name,
                "tc_seconds": tc_seconds,
                "tc_increment": tc_increment,
            }
            await self.li.create_challenge(challenge)
            return
