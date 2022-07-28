import argparse
import asyncio
import sys
from argparse import ArgumentParser
from typing import NoReturn

import chess.engine
import loguru
from loguru import logger

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
    log_level = "DEBUG" if args.verbose else "INFO"

    logger.remove()
    logger.add(sys.stderr, level=log_level)
    if args.log:
        logger.add(args.log, level=log_level)

    logger.info(LOGO)

    li = Lichess()

    if args.upgrade:
        if li.title == "BOT":
            logger.warning("Account is already a BOT.")
        else:
            if await li.upgrade_account():
                logger.info("BOT upgrade successful.")
            else:
                logger.info("BOT upgrade failed.")
        return

    if li.title != "BOT":
        logger.error("asyncLio-bot can only be used by BOT accounts.")
        return

    logger.info(f"Logged in as {li.title} {li.username}")

    event_handler = EventHandler(li)
    await event_handler.run()


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--upgrade", "-u", action="store_true", help="Upgrade account to BOT account."
    )
    parser.add_argument("--log", "-l", type=str, help="Log file.")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Make output more verbose."
    )

    asyncio.set_event_loop_policy(chess.engine.EventLoopPolicy())
    asyncio.run(main(parser.parse_args()))
