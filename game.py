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
        self.white_clock: int = 0
        self.black_clock: int = 0
        self.white_inc: int = 0
        self.black_inc: int = 0
        self.engine: chess.engine.UciProtocol | None = None
        self.loop_task: asyncio.Task | None = None

    def __str__(self) -> str:
        white_name, black_name = self.player_names
        return f"{self.id} -- {white_name} v. {black_name}"

    @property
    def me(self) -> str:
        return f"{self.li.title} {self.li.username}"

    @property
    def player_names(self) -> tuple[str, str]:
        if self.color == chess.WHITE:
            return self.me, self.opponent
        elif self.color == chess.BLACK:
            return self.opponent, self.me
        raise ValueError("Colors unknown.")

    @property
    def is_our_turn(self) -> bool:
        return self.color == self.board.turn

    @property
    def is_game_over(self) -> bool:
        return self.status not in (GameStatus.STARTED, GameStatus.CREATED)

    async def start_engine(self) -> None:
        logger.debug(f"{self.id} -- Starting engine {CONFIG['engine']['path']}.")
        try:
            transport, engine = await chess.engine.popen_uci(CONFIG["engine"]["path"])
            if options := CONFIG["engine"].get("uci_options"):
                await engine.configure(options)
        except Exception as e:
            logger.critical(f"{self.id} -- {e}")
            sys.exit()
        self.engine = engine

    def update(self, event: dict) -> bool:
        self.status = GameStatus(event["status"])
        self.white_clock = event["wtime"]
        self.black_clock = event["btime"]
        self.white_inc = event["winc"]
        self.black_inc = event["binc"]

        moves = event["moves"].split()
        if len(moves) <= len(self.board.move_stack):
            return False

        self.board = self.setup_board(moves)
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

        return "{id} -- Engine: {move_number}{ellipses} {move:<10}Score: {score!s:<10}Time: {time:<10.1f}Depth: {depth:<10}PV: {pv!s:<30}".format(
            id=self.id,
            move_number=self.board.fullmove_number,
            ellipses="." if self.board.turn == chess.WHITE else "...",
            move=self.board.san(move),
            score=score.pov(self.color) if (score := info.get("score")) else None,
            time=info.get("time", 0.0),
            depth=info.get("depth", 1),
            pv=self.board.variation_san(pv) if (pv := info.get("pv")) else None,
        )

    def format_result_message(self, event: dict) -> str:

        if winning_color := event.get("winner"):
            white_name, black_name = self.player_names
            winning_name = white_name if winning_color == "white" else black_name
            losing_name = white_name if winning_color == "black" else black_name

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
        return f"{self.id} -- {message}"

    def get_book_move(self) -> chess.Move:
        if not CONFIG["books"]["enabled"]:
            return chess.Move.null()

        if self.board.ply() > CONFIG["books"].get("depth", 10):
            return chess.Move.null()

        if self.board.uci_variant == "chess" and (
            standard_paths := CONFIG["books"].get("standard")
        ):
            books = standard_paths
        elif variant_paths := CONFIG["books"].get(self.board.uci_variant):
            books = variant_paths
        else:
            return chess.Move.null()

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
                except IndexError:
                    continue
                board.push(move)
                if not board.is_repetition(count=2):
                    return move
                board.pop()

        return chess.Move.null()

    async def get_engine_move(self) -> tuple[chess.Move, chess.engine.InfoDict]:
        if len(self.board.move_stack) < 2:
            limit = chess.engine.Limit(time=10)
        else:
            limit = chess.engine.Limit(
                white_clock=max(self.white_clock - CONFIG.get("move_overhead", 0), 0)
                / 1000,
                black_clock=max(self.black_clock - CONFIG.get("move_overhead", 0), 0)
                / 1000,
                white_inc=self.white_inc / 1000,
                black_inc=self.black_inc / 1000,
            )

        result = await self.engine.play(self.board, limit, info=chess.engine.INFO_ALL)

        if not result.move:
            e = RuntimeError("Engine could not make a move.")
            logger.error(e)
            raise

        if score := result.info.get("score"):
            self.scores.append(score)
        else:
            self.scores.append(
                chess.engine.PovScore(chess.engine.Mate(1), self.board.turn)
            )

        return result.move, result.info

    async def make_move(self) -> None:
        resign = False
        offer_draw = False
        if move := self.get_book_move():
            message = f"{self.id} -- Book: {self.board.fullmove_number}{'.' if self.board.turn == chess.WHITE else '...'} {self.board.san(move)}"
        else:
            logger.info(f"{self.id} -- Searching for move from {self.board.fen()}.")
            move, info = await self.get_engine_move()
            message = self.format_engine_move_message(move, info)
            resign = self.should_resign()
            offer_draw = self.should_draw()

        logger.info(message)

        if self.is_game_over:
            return

        if resign:
            logger.info(f"{self.id} -- Resigning game.")
            await self.li.resign_game(self.id)
        else:
            if offer_draw:
                logger.info(f"{self.id} -- Offering draw.")
            await self.li.make_move(self.id, move, offer_draw=offer_draw)

    def start(self) -> None:
        self.loop_task = asyncio.create_task(self.watch_game_loop())

    async def watch_game_loop(self):
        await self.start_engine()
        start_time = time.monotonic()
        move_tasks = []
        async for event in self.li.game_stream(self.id):
            event_type = GameEvent(event["type"])

            if event_type == GameEvent.GAME_FULL:
                self.update(event["state"])

                # Only make a move here if it's our turn, and we haven't made a move since entering the loop.
                if self.is_our_turn and not self.is_game_over and len(move_tasks) == 0:
                    move_tasks.append(asyncio.create_task(self.make_move()))

            elif event_type == GameEvent.GAME_STATE:
                board_updated = self.update(event)

                if self.is_game_over:
                    logger.info(self.format_result_message(event))
                    break

                if self.is_our_turn and board_updated:
                    move_tasks.append(asyncio.create_task(self.make_move()))

            elif event_type == GameEvent.PING:
                if (
                    len(self.board.move_stack) < 2
                    and not self.is_our_turn
                    and time.monotonic() > start_time + CONFIG["abort_time"]
                ):
                    await self.li.abort_game(self.id)

        # Just in case we've reached this stage unexpectedly.
        if not self.is_game_over:
            self.status = GameStatus.UNKNOWN_FINISH

        logger.debug(f"{self.id} -- Quitting engine.")
        await self.engine.quit()
