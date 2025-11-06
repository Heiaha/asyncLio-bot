import asyncio
import logging
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
        self.status: GameStatus = GameStatus(event["game"]["status"]["name"])
        self.scores: list[chess.engine.PovScore] = []
        self.board: chess.Board = self.make_board()
        self.ponder_move: chess.Move | None = None

        # attributes to be set up asynchronously or after the game starts
        self.clock: dict[str, float] = {
            "white_clock": 0,
            "black_clock": 0,
            "white_inc": 0,
            "black_inc": 0,
        }
        self.engine: chess.engine.UciProtocol | None = None
        self.loop_task: asyncio.Task | None = None

    def __str__(self) -> str:
        white_name, black_name = self.player_names
        return f"{self.id} -- {self.variant}: {white_name} v. {black_name}"

    @property
    def player_names(self) -> tuple[str, str]:
        if self.color == chess.WHITE:
            return self.li.me, self.opponent
        elif self.color == chess.BLACK:
            return self.opponent, self.li.me
        raise ValueError("Colors unknown.")

    @property
    def is_our_turn(self) -> bool:
        return self.color == self.board.turn

    @property
    def is_game_over(self) -> bool:
        return self.status not in (GameStatus.STARTED, GameStatus.CREATED)

    async def start_engine(self) -> None:
        logger.debug(f"{self.id} -- Starting engine {CONFIG['engine']['path']}.")
        transport, engine = await chess.engine.popen_uci(CONFIG["engine"]["path"])
        if options := CONFIG["engine"].get("uci_options"):
            await engine.configure(options)
        self.engine = engine

    def update(self, event: dict) -> bool:
        self.status = GameStatus(event["status"])

        self.clock = {
            "white_clock": event["wtime"] / 1000,
            "black_clock": event["btime"] / 1000,
            "white_inc": event["winc"] / 1000,
            "black_inc": event["binc"] / 1000,
        }

        moves = event["moves"].split()
        if len(moves) <= len(self.board.move_stack):
            return False

        self.board = self.make_board(moves)
        return True

    def make_board(self, moves: list[str] | None = None) -> chess.Board:
        if self.variant == Variant.CHESS960:
            board = chess.Board(self.initial_fen, chess960=True)
        elif self.variant == Variant.FROM_POSITION:
            board = chess.Board(self.initial_fen)
        else:
            VariantBoard = chess.variant.find_variant(self.variant)
            board = VariantBoard()

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

    def format_book_move_message(self, move: chess.Move) -> str:
        return "{id} -- Book: {move_number}{ellipses} {move}".format(
            id=self.id,
            move_number=self.board.fullmove_number,
            ellipses="." if self.board.turn == chess.WHITE else "...",
            move=move.uci(),
        )

    def format_engine_move_message(
        self, move: chess.Move, info: chess.engine.InfoDict, search_time: float
    ) -> str:
        return "{id} -- Engine: {move_number}{ellipses} {move:<10}Score: {score!s:<10}Time: {time:<10.1f}Depth: {depth:<10}NPS: {nps:<15}PV: {pv!s:<30}".format(
            id=self.id,
            move_number=self.board.fullmove_number,
            ellipses="." if self.board.turn == chess.WHITE else "...",
            move=move.uci(),
            score=score.pov(self.color) if (score := info.get("score")) else None,
            time=search_time,
            depth=info.get("depth", 1),
            nps=info.get("nps", 0),
            pv=" ".join(m.uci() for m in pv) if (pv := info.get("pv")) else None,
        )

    def format_result_message(self, event: dict) -> str:
        if wb_winner := event.get("winner"):
            white_name, black_name = self.player_names
            winning_name, losing_name = (
                (white_name, black_name)
                if wb_winner == "white"
                else (black_name, white_name)
            )

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

    def should_use_book(self):
        if not CONFIG["books"]["enabled"]:
            return False

        return self.board.fullmove_number <= CONFIG["books"].get("depth", 10)

    def get_book_move(self) -> chess.Move | None:
        books = CONFIG["books"].get(
            Variant.STANDARD if self.variant == Variant.FROM_POSITION else self.variant
        )

        if not books:
            return None

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
        return None

    async def get_engine_move(self) -> (chess.Move, chess.engine.InfoDict):
        clock = self.clock.copy()

        clock_name = "white_clock" if self.color == chess.WHITE else "black_clock"
        clock[clock_name] = max(
            0, clock[clock_name] - CONFIG.get("move_overhead", 0) / 1000
        )

        limit = (
            chess.engine.Limit(**clock)
            if len(self.board.move_stack) >= 2
            else chess.engine.Limit(time=10)
        )

        result = await self.engine.play(
            self.board,
            limit=limit,
            info=chess.engine.INFO_ALL,
            ponder=CONFIG["engine"].get("ponder", False),
        )

        self.ponder_move = result.ponder

        if not result.move:
            raise RuntimeError(f"{self.id} -- Engine could not make a move.")

        self.scores.append(
            result.info.get(
                "score", chess.engine.PovScore(chess.engine.MateGiven, self.board.turn)
            )
        )

        return result.move, result.info

    async def make_move(self) -> None:
        ponder_result_str = ""
        if len(self.board.move_stack) > 0 and self.ponder_move == self.board.peek():
            ponder_result_str = "Ponder Hit."
        elif self.ponder_move is not None:
            ponder_result_str = "Ponder Miss."

        logger.info(
            f"{self.id} -- Searching for move from {self.board.fen()}. {ponder_result_str}"
        )
        self.ponder_move = None

        if self.should_use_book() and (move := self.get_book_move()):
            logger.info(self.format_book_move_message(move))
            await self.li.make_move(self.id, move)
            return

        try:
            search_start_time = time.monotonic()
            move, info = await self.get_engine_move()
            search_end_time = time.monotonic()

            logger.info(
                self.format_engine_move_message(
                    move, info, search_end_time - search_start_time
                )
            )
        except chess.engine.EngineTerminatedError:
            # We may get a chess.engine.EngineTerminatedError if the game ends (and engine is quit) while searching.
            # If that's the case, don't log it as an error.
            if not self.is_game_over:
                await self.li.resign_game(self.id)
                raise
            return

        if self.is_game_over:
            return

        if self.should_resign():
            logger.info(f"{self.id} -- Resigning game.")
            await self.li.resign_game(self.id)
            return

        offer_draw = self.should_draw()
        if offer_draw:
            logger.info(f"{self.id} -- Offering draw.")

        await self.li.make_move(self.id, move, offer_draw=offer_draw)

    def start(self) -> None:
        self.loop_task = asyncio.create_task(self.watch_game_stream())

    async def watch_game_stream(self) -> None:
        start_time = time.monotonic()
        move_tasks = []
        await self.start_engine()
        async for event in self.li.game_stream(self.id):
            event_type = GameEvent(event["type"])
            should_make_move = False

            if event_type == GameEvent.GAME_FULL:
                self.update(event["state"])
                should_make_move = self.is_our_turn

            elif event_type == GameEvent.GAME_STATE:
                should_make_move = self.update(event) and self.is_our_turn

            elif event_type == GameEvent.OPPONENT_GONE:
                if event.get("claimWinInSeconds") == 0 and not self.is_our_turn:
                    logger.info(f"{self.id} -- Attempting to claim victory.")
                    await self.li.claim_victory(self.id)

            elif event_type == GameEvent.PING:
                if (
                    len(self.board.move_stack) < 2
                    and not self.is_our_turn
                    and time.monotonic() - start_time >= CONFIG["abort_time"]
                ):
                    await self.li.abort_game(self.id)

            if self.is_game_over:
                logger.info(self.format_result_message(event.get("state", event)))
                break

            if should_make_move:
                await asyncio.gather(*move_tasks)
                move_tasks.append(asyncio.create_task(self.make_move()))

        # Just in case we've reached this stage unexpectedly.
        if not self.is_game_over:
            self.status = GameStatus.UNKNOWN_FINISH

        await self.engine.quit()
        await asyncio.gather(*move_tasks)
