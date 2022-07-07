import asyncio

from event_handler import EventHandler
from lichess import Lichess


async def main():

    li = await Lichess.create()

    event_handler = EventHandler(li)
    await event_handler.run()


if __name__ == "__main__":
    asyncio.run(main())
