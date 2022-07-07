import asyncio

from game_manager import GameManager
from lichess import Lichess


class EventHandler:
    def __init__(self, li: Lichess):
        self.li: Lichess = li
        self.game_manager: GameManager = GameManager(li)

    async def run(self):
        asyncio.create_task(self.game_manager.run())
        async for event in self.li.watch_control_stream():
            if event["type"] == "ping":
                continue

            elif event["type"] == "gameStart":
                self.game_manager.on_game_start(event)

            elif event["type"] == "gameFinish":
                self.game_manager.on_game_finish()

            elif event["type"] == "challenge":
                await self.game_manager.on_challenge(event)

            elif event["type"] == "challengeDeclined":
                continue
