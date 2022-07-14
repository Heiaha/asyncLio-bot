import time
import chess
import chess.engine
import chess.polyglot
import chess.variant
import logging

from config import CONFIG
from enums import GameStatus, GameEvent, Variant
from lichess import Lichess


class Game:
    def __init__(self, li: Lichess, game_id: str):
        self.li: Lichess = li
        self.id: str = game_id
        self.status: GameStatus = GameStatus.CREATED
        self.board: chess.Board = chess.Board()

        # attributes to be set up asynchronously when the game starts
        self.color: chess.Color | None = None
        self.initial_fen: str | None = None
        self.white_time: int | None = None
        self.black_time: int | None = None
        self.increment: int | None = None
        self.white_name: str | None = None
        self.black_name: str | None = None
        self.variant: Variant | None = None
        self.engine: chess.engine.UciProtocol | None = None

    async def _setup(self, event):
        if (fen := event["initialFen"]) != "startpos":
            self.initial_fen = fen
        else:
            self.initial_fen = chess.STARTING_FEN

        self.white_time = event["state"]["wtime"]
        self.black_time = event["state"]["btime"]
        self.increment = event["clock"]["increment"]
        self.white_name = event["white"].get("name", "AI")
        self.black_name = event["black"].get("name", "AI")
        self.status = GameStatus(event["state"]["status"])
        self.variant = Variant(event["variant"]["key"])
        self.color = chess.WHITE if self.white_name == self.li.username else chess.BLACK

        self.board = self._setup_board(event["state"])

        transport, engine = await chess.engine.popen_uci(CONFIG["engine"]["path"])
        if options := CONFIG["engine"].get("uci_options"):
            await engine.configure(options)
        self.engine = engine
        self.start_time = time.monotonic()

    def _update(self, event: dict):

        self.board = self._setup_board(event)
        self.white_time = event["wtime"]
        self.black_time = event["btime"]
        self.status = GameStatus(event["status"])

    def _setup_board(self, event: dict) -> chess.Board:
        if self.variant == Variant.CHESS960:
            board = chess.Board(self.initial_fen, chess960=True)
        elif self.variant == Variant.FROM_POSITION:
            board = chess.Board(self.initial_fen)
        else:
            board = chess.variant.find_variant(self.variant.value)()

        move_strs = event["moves"].split()
        for move_str in move_strs:
            board.push_uci(move_str)

        return board

    def _is_our_turn(self) -> bool:
        return self.color == self.board.turn

    def _get_book_move(self) -> chess.Move | None:
        if not CONFIG["book"]["enabled"]:
            return

        if self.board.chess960 and (chess960_path := CONFIG["book"].get("chess960")):
            book_path = chess960_path
        elif standard_path := CONFIG["book"].get("standard"):
            book_path = standard_path
        else:
            return

        if self.board.ply() > CONFIG["book"].get("depth", 10):
            return

        with chess.polyglot.open_reader(book_path) as reader:
            try:
                move = reader.weighted_choice(self.board).move
                new_board = self.board.copy()
                new_board.push(move)
                if not new_board.is_repetition(count=2):
                    return move
            except IndexError:
                return

    async def _get_engine_move(self) -> tuple[chess.Move, chess.engine.InfoDict]:
        if len(self.board.move_stack) < 2:
            limit = chess.engine.Limit(time=10)
        else:
            limit = chess.engine.Limit(
                white_clock=self.white_time / 1000,
                black_clock=self.black_time / 1000,
                white_inc=self.increment / 1000,
                black_inc=self.increment / 1000,
            )

        result = await self.engine.play(self.board, limit, info=chess.engine.INFO_ALL)
        if result.move:
            return result.move, result.info
        raise RuntimeError("Engine could not make a move.")

    async def _make_move(self):
        if move := self._get_book_move():
            message = f"{self.id} -- Book: {self.board.san(move)}"
        else:
            logging.info(
                f"Searching for move in game {self.id} from {self.board.fen()}"
            )
            move, info = await self._get_engine_move()
            message = self._format_engine_move_message(move, info)

        logging.info(message)
        await self.li.make_move(self.id, move)

    def _format_engine_move_message(
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

    def _format_result_message(self, winner: str | None) -> str:
        winning_name = self.white_name if winner == "white" else self.black_name
        losing_name = self.white_name if winner == "black" else self.black_name

        if winner:
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
        else:
            message = "Game aborted."
        return message

    def is_game_over(self) -> bool:
        return self.status not in (GameStatus.STARTED, GameStatus.CREATED)

    async def play(self):
        abort_count = 0
        async for event in self.li.watch_game_stream(self.id):
            event_type = GameEvent(event["type"])
            if event_type == GameEvent.GAME_FULL:
                # on lichess restarts a gameFull message will be sent, even if the game is underway.
                # check if we've already done a setup
                if self.status == GameStatus.CREATED:
                    await self._setup(event)
                else:
                    self._update(event["state"])

                if self._is_our_turn():
                    await self._make_move()

            elif event_type == GameEvent.GAME_STATE:
                self._update(event)

                if self.is_game_over():
                    message = self._format_result_message(event.get("winner"))
                    logging.info(message)
                    break

                if self._is_our_turn():
                    await self._make_move()

            elif event_type == GameEvent.PING:
                if (
                    len(self.board.move_stack) < 2
                    and not self._is_our_turn()
                    and time.monotonic() > self.start_time + CONFIG["abort_time"]
                ):
                    await self.li.abort_game(self.id)
                    abort_count += 1

                    # If we've tried to abort the game three times and still haven't gotten back
                    # a game event about the abort, just break out of the loop.
                    if abort_count >= 3:
                        self.status = GameStatus.ABORTED
                        break

        # It's possible we've reached this stage because the server has 502'd
        # and the iterator has unexpectedly closed without setting the status to be in a finished state.
        # If that's true we need to set the game to be over, so that it can be cleaned up by the game manager.
        if not self.is_game_over():
            self.status = GameStatus.UNKNOWN_FINISH

        logging.info("Quitting engine.")
        await self.engine.quit()
