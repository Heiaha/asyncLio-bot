import asyncio
from typing import NoReturn

from enums import Event
from game_manager import GameManager
from lichess import Lichess


class EventHandler:
    def __init__(self, li: Lichess) -> None:
        self.li: Lichess = li
        self.game_manager: GameManager = GameManager(li)

    async def run(self) -> NoReturn:
        asyncio.create_task(self.game_manager.run())
        async for event in self.li.watch_event_stream():
            event_type = Event(event["type"])
            if event_type == Event.PING:
                self.game_manager.clean_games()
                continue

            elif event_type == Event.GAME_START:
                await self.game_manager.on_game_start(event)

            elif event_type == Event.GAME_FINISH:
                await self.game_manager.on_game_finish(event)

            elif event_type == Event.CHALLENGE:
                await self.game_manager.on_challenge(event)

            elif event_type == Event.CHALLENGE_DECLINED:
                continue

            elif event_type == Event.CHALLENGE_CANCELED:
                self.game_manager.on_challenge_cancelled(event)
