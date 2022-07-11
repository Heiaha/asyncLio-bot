import asyncio
import logging
import chess.engine
from event_handler import EventHandler
from lichess import Lichess


async def main():
    logging.basicConfig(
        # filename="logs.log",
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    li = await Lichess.create()
    logging.info(f"Logged in as {li.username}")

    event_handler = EventHandler(li)
    await event_handler.run()


if __name__ == "__main__":
    asyncio.set_event_loop_policy(chess.engine.EventLoopPolicy())
    asyncio.run(main(), debug=True)
