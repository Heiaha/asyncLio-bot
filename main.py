import argparse
import asyncio
import logging
from argparse import ArgumentParser
from typing import NoReturn

import chess.engine

from event_handler import EventHandler
from lichess import Lichess

LOGO = """
                              __ _             _           _   
  __ _ ___ _   _ _ __   ___  / /(_) ___       | |__   ___ | |_ 
 / _` / __| | | | '_ \ / __|/ / | |/ _ \ _____| '_ \ / _ \| __|
| (_| \__ \ |_| | | | | (__/ /__| | (_) |_____| |_) | (_) | |_ 
 \__,_|___/\__, |_| |_|\___\____/_|\___/      |_.__/ \___/ \__|
           |___/                                               
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

    li = Lichess()

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
        logging.error("asyncLio-bot can only be used by BOT accounts.")
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
