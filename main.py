import asyncio
import yaml
from lichess import Lichess
from event_handler import EventHandler
from game_manager import GameManager
from matchmaker import Matchmaker


async def main():

    with open("config.yml", "r") as config_file:
        config = yaml.safe_load(config_file)

    li = await Lichess.create(config)

    event_handler = EventHandler(li, config)
    await event_handler.run()


if __name__ == "__main__":
    asyncio.run(main())
