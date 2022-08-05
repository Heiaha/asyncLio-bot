import asyncio
import logging
import sys
import time

import chess
import chess.engine
import chess.polyglot
import chess.variant

from config import CONFIG
from enums import GameStatus, GameEvent, Variant, BookSelection
from lichess import Lichess

logger = logging.getLogger(__name__)


class Game:
    def __init__(self, li: Lichess, event: dict) -> None:
        self.li: Lichess = li
        self.id: str = event["game"]["gameId"]
        self.color: chess.Color = (
            chess.WHITE if event["game"]["color"] == "white" else chess.BLACK
        )
        self.opponent: str = event["game"]["opponent"]["username"]
        self.initial_fen: str = event["game"]["fen"]
        self.variant: Variant = Variant(event["game"]["variant"]["key"])
        self.status: GameStatus = GameStatus.CREATED
        self.scores: list[chess.engine.PovScore] = []
        self.board: chess.Board = self.setup_board()

        # attributes to be set up asynchronously or after the game starts
        self.loop_task: asyncio.Task | None = None
        self.move_task: asyncio.Task | None = None
        self.start_time: float | None = None
        self.white_time: int | None = None
        self.black_time: int | None = None
        self.white_inc: int | None = None
        self.black_inc: int | None = None
        self.engine: chess.engine.UciProtocol | None = None

    async def setup(self) -> None:
        logger.debug(f"Starting engine {CONFIG['engine']['path']}.")
        try:
            transport, engine = await chess.engine.popen_uci(CONFIG["engine"]["path"])
            if options := CONFIG["engine"].get("uci_options"):
                await engine.configure(options)
        except Exception as e:
            logger.critical(e)
            sys.exit()
        self.engine = engine
        self.start_time = time.monotonic()

    def update(self, event: dict) -> bool:
        self.status = GameStatus(event["status"])

        moves = event["moves"].split()
        if len(moves) <= len(self.board.move_stack):
            return False

        self.board = self.setup_board(moves)
        self.white_time = event["wtime"]
        self.black_time = event["btime"]
        self.white_inc = event["winc"]
        self.black_inc = event["binc"]
        return True

    def setup_board(self, moves: list[str] | None = None) -> chess.Board:
        if self.variant == Variant.CHESS960:
            board = chess.Board(self.initial_fen, chess960=True)
        elif self.variant == Variant.FROM_POSITION:
            board = chess.Board(self.initial_fen)
        else:
            variant_board_type = chess.variant.find_variant(self.variant.value)
            board = variant_board_type()

        if moves:
            for move in moves:
                board.push_uci(move)
        return board

    def is_our_turn(self) -> bool:
        return self.color == self.board.turn

    def get_book_move(self) -> chess.Move | None:
        if not CONFIG["books"]["enabled"]:
            return

        if self.board.ply() > CONFIG["books"].get("depth", 10):
            return

        if self.board.uci_variant == "chess" and (
            standard_paths := CONFIG["books"].get("standard")
        ):
            books = standard_paths
        elif variant_paths := CONFIG["books"].get(self.board.uci_variant):
            books = variant_paths
        else:
            return

        selection = BookSelection(CONFIG["books"]["selection"])
        board = self.board.copy()
        for book in books:
            with chess.polyglot.open_reader(book) as reader:
                try:
                    if selection == BookSelection.WEIGHTED_RANDOM:
                        move = reader.weighted_choice(board).move
                    elif selection == BookSelection.UNIFORM_RANDOM:
                        move = reader.choice(board).move
                    elif selection == BookSelection.BEST_MOVE:
                        move = reader.find(board).move
                    board.push(move)
                    if not board.is_repetition(count=2):
                        return move
                    board.pop()
                except IndexError:
                    pass

    async def get_engine_move(self) -> tuple[chess.Move, chess.engine.InfoDict]:
        if len(self.board.move_stack) < 2:
            limit = chess.engine.Limit(time=10)
        else:
            limit = chess.engine.Limit(
                white_clock=max(self.white_time - CONFIG.get("move_overhead", 0), 0)
                / 1000,
                black_clock=max(self.black_time - CONFIG.get("move_overhead", 0), 0)
                / 1000,
                white_inc=self.white_inc / 1000,
                black_inc=self.black_inc / 1000,
            )

        result = await self.engine.play(self.board, limit, info=chess.engine.INFO_ALL)
        if result.move:
            score = result.info.get(
                "score", chess.engine.PovScore(chess.engine.Mate(1), self.board.turn)
            )
            self.scores.append(score)
            return result.move, result.info

        raise RuntimeError("Engine could not make a move.")

    async def make_move(self) -> None:
        resign = False
        offer_draw = False
        if move := self.get_book_move():
            message = f"{self.id} -- Book: {self.board.san(move)}"
        else:
            logger.info(f"{self.id} -- Searching for move from {self.board.fen()}.")
            move, info = await self.get_engine_move()
            message = self.format_engine_move_message(move, info)
            resign = self.should_resign()
            offer_draw = self.should_draw()

        if self.is_game_over():
            return

        if resign:
            logger.info(f"Resigning game {self.id}.")
            await self.li.resign_game(self.id)
        else:
            logger.info(message)
            await self.li.make_move(self.id, move, offer_draw=offer_draw)

    def should_draw(self) -> bool:
        if not CONFIG["draw"]["enabled"]:
            return False

        if self.board.fullmove_number < CONFIG["draw"]["min_game_length"]:
            return False

        if len(self.scores) < CONFIG["draw"]["moves"]:
            return False

        return all(
            abs(score.relative) <= chess.engine.Cp(CONFIG["draw"]["score"])
            for score in self.scores[-CONFIG["draw"]["moves"] :]
        )

    def should_resign(self) -> bool:
        if not CONFIG["resign"]["enabled"]:
            return False

        if len(self.scores) < CONFIG["resign"]["moves"]:
            return False

        return all(
            score.relative <= chess.engine.Cp(CONFIG["resign"]["score"])
            for score in self.scores[-CONFIG["resign"]["moves"] :]
        )

    def format_engine_move_message(
        self, move: chess.Move, info: chess.engine.InfoDict
    ) -> str:
        message = f"{self.id} -- Engine: "
        if self.board.turn:
            move_number = str(self.board.fullmove_number) + "."
            message += f"{move_number:4} {self.board.san(move):<10}"
        else:
            move_number = str(self.board.fullmove_number) + "..."
            message += f"{move_number:6} {self.board.san(move):<10}"

        if score := info.get(
            "score", chess.engine.PovScore(chess.engine.Cp(0), self.color)
        ):
            if moves_to_go := score.pov(self.color).mate():
                moves_to_go_str = (
                    f"+{moves_to_go}" if moves_to_go > 0 else f"{moves_to_go}"
                )
                message += f"Mate: {moves_to_go_str:<10}"
            else:
                if (cp_score := score.pov(self.board.turn).score()) is not None:
                    score_str = f"+{cp_score}" if cp_score > 0 else f"{cp_score}"
                    message += f"CP Score: {score_str:<10}"

        if think_time := info.get("time", 0.0):
            message += f"Time: {think_time:<10.1f}"

        if depth := info.get("depth", 1):
            message += f"Depth: {depth:<10}"

        if pv := info.get("pv"):
            message += f"PV: {self.board.variation_san(pv)}"

        return message

    def format_result_message(self, winner_str: str | None) -> str:

        if winner_str == "white":
            winner = chess.WHITE
        elif winner_str == "black":
            winner = chess.BLACK
        else:
            winner = None

        winning_name = self.li.username if winner == self.color else self.opponent
        losing_name = self.opponent if winner == self.color else self.li.username

        if winner is not None:
            message = f"{winning_name} won"

            if self.status == GameStatus.MATE:
                message += " by checkmate!"
            elif self.status == GameStatus.OUT_OF_TIME:
                message += f"! {losing_name} ran out of time."
            elif self.status == GameStatus.RESIGN:
                message += f"! {losing_name} resigned."
        elif self.status == GameStatus.DRAW:
            if self.board.is_fifty_moves():
                message = "Game drawn by 50-move rule."
            elif self.board.is_repetition():
                message = "Game drawn by threefold repetition."
            elif self.board.is_insufficient_material():
                message = "Game drawn due to insufficient material."
            else:
                message = "Game drawn by agreement."
        elif self.status == GameStatus.STALEMATE:
            message = "Game drawn by stalemate."
        elif self.status == GameStatus.ABORTED:
            message = "Game aborted."
        else:
            message = "Game finish unknown."
        return message

    async def _play(self):
        abort_count = 0
        await self.setup()
        async for event in self.li.watch_game_stream(self.id):
            event_type = GameEvent(event["type"])

            if event_type == GameEvent.GAME_FULL:
                self.update(event["state"])
                if self.is_our_turn():
                    self.move_task = asyncio.create_task(self.make_move())

            elif event_type == GameEvent.GAME_STATE:
                updated = self.update(event)

                if self.is_game_over():
                    message = self.format_result_message(event.get("winner"))
                    logger.info(message)
                    break

                if self.is_our_turn() and updated:
                    self.move_task = asyncio.create_task(self.make_move())

            elif event_type == GameEvent.PING:
                if (
                    len(self.board.move_stack) < 2
                    and not self.is_our_turn()
                    and time.monotonic() > self.start_time + CONFIG["abort_time"]
                ):
                    await self.li.abort_game(self.id)
                    abort_count += 1

                    # If we've tried to abort the game three times and still haven't gotten back
                    # a game event about the abort, just break out of the loop.
                    if abort_count >= 3:
                        self.status = GameStatus.ABORTED
                        break

        # It's possible we've reached this stage because the server has > 500'd
        # and the iterator has unexpectedly closed without setting the status to be in a finished state.
        # If that's true we need to set the game to be over, so that it can be cleaned up by the game manager.
        if not self.is_game_over():
            self.status = GameStatus.UNKNOWN_FINISH

        if self.move_task:
            # Try to have the most recent move task exit gracefully before trying to cancel it.
            try:
                await asyncio.wait_for(self.move_task, timeout=60)
            except asyncio.TimeoutError:
                self.move_task.cancel()

        logger.debug("Quitting engine.")
        await self.engine.quit()

    def is_game_over(self) -> bool:
        return self.status not in (GameStatus.STARTED, GameStatus.CREATED)

    def play(self) -> None:
        self.loop_task = asyncio.create_task(self._play())
