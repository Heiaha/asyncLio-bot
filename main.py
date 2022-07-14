import argparse
import asyncio
import logging
from argparse import ArgumentParser
from typing import NoReturn

import chess.engine

from event_handler import EventHandler
from lichess import Lichess

LOGO = """
  _    _                               _ 
 | |  | |                             | |
 | |__| | ___ _ __ _ __ ___   ___   __| |
 |  __  |/ _ \ '__| '_ ` _ \ / _ \ / _` |
 | |  | |  __/ |  | | | | | | (_) | (_| |
 |_|  |_|\___|_|  |_| |_| |_|\___/ \__,_|
                                         
                                         """


async def main(args: argparse.Namespace) -> NoReturn:
    logging_handlers = [logging.StreamHandler()]
    if args.log:
        logging_handlers.append(logging.FileHandler(args.log))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=logging_handlers,
    )
    logging.info(LOGO)
    li = await Lichess.create()

    if args.upgrade:
        if li.title == "BOT":
            logging.warning("Account is already a BOT.")
        else:
            if await li.upgrade_account():
                logging.info("BOT upgrade successful.")
            else:
                logging.info("BOT upgrade failed.")
        return

    if li.title != "BOT":
        logging.error("Hermod can only be used by BOT accounts.")
        return

    logging.info(f"Logged in as {li.title} {li.username}")

    event_handler = EventHandler(li)
    await event_handler.run()


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--upgrade", "-u", action="store_true", help="Upgrade account to BOT account."
    )
    parser.add_argument("--log", "-l", type=str, help="Log file.")

    asyncio.set_event_loop_policy(chess.engine.EventLoopPolicy())
    asyncio.run(main(parser.parse_args()))
