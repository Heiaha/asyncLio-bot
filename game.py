import chess
import chess.engine
import chess.polyglot

from config import CONFIG
from enums import GameStatus
from lichess import Lichess


class Game:
    def __init__(self, li: Lichess, game_id: str):
        self.li: Lichess = li
        self.id: str = game_id
        self.board: chess.Board = chess.Board()

        # attributes to be set up asynchronously or when the game starts
        self.color: chess.Color | None = None
        self.initial_fen: str | None = None
        self.white_time: int | None = None
        self.black_time: int | None = None
        self.increment: int | None = None
        self.white_name: str | None = None
        self.black_name: str | None = None
        self.status: GameStatus | None = None
        self.engine: chess.engine.UciProtocol | None = None

    async def _setup(self, event):
        if (fen := event["initialFen"]) != "startpos":
            self.initial_fen = fen
            self.board = chess.Board(fen)
        self.white_time = event["state"]["wtime"]
        self.black_time = event["state"]["btime"]
        self.increment = event["clock"]["increment"]
        self.white_name = event["white"].get("name", "AI")
        self.black_name = event["black"].get("name", "AI")
        self.status = GameStatus(event["state"]["status"])
        self.color = chess.WHITE if self.white_name == self.li.username else chess.BLACK

        transport, engine = await chess.engine.popen_uci(CONFIG["engine"]["path"])
        await engine.configure(CONFIG["engine"]["uci_options"])
        self.engine = engine

    def _update(self, event):

        if self.initial_fen:
            self.board = chess.Board(self.initial_fen)
        else:
            self.board = chess.Board()

        move_strs = event["moves"].split()
        for move_str in move_strs:
            self.board.push_uci(move_str)

        self.white_time = event["wtime"]
        self.black_time = event["btime"]
        self.status = GameStatus(event["status"])

    def _is_game_over(self):
        return self.status != GameStatus.STARTED

    def _is_our_turn(self):
        return self.color == self.board.turn

    def _make_book_move(self) -> chess.Move | None:
        if self.board.ply() > CONFIG["book"]["depth"]:
            return
        with chess.polyglot.open_reader("komodo.bin") as reader:
            try:
                move = reader.weighted_choice(self.board).move
                new_board = self.board.copy()
                new_board.push(move)
                if not new_board.is_repetition(count=2):
                    return move
            except IndexError:
                pass

    async def _make_engine_move(self):
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
        if move := self._make_book_move():
            message = f"Book: {move.uci()}"
        else:
            move, info = await self._make_engine_move()
            message = f"Engine {move.uci()} {info}"

        print(message)
        await self.li.make_move(self.id, move)

    def _get_result_message(self, winner: str | None) -> str:
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

    async def play(self):
        try:
            ping_counter = 0
            async for event in self.li.watch_game_stream(self.id):
                if event["type"] == "gameFull":
                    # on lichess restarts a gameFull message will be sent, even if the game is underway.
                    # check if we've already done a setup
                    if self.status is None:
                        await self._setup(event)
                    else:
                        self._update(event["state"])

                    if self._is_our_turn():
                        await self._make_move()

                elif event["type"] == "gameState":
                    self._update(event)

                    if self._is_game_over():
                        print(self._get_result_message(event.get("winner")))
                        break

                    if self._is_our_turn():
                        await self._make_move()

                elif event["type"] == "ping":
                    ping_counter += 1

                    if (
                        ping_counter >= 7
                        and len(self.board.move_stack) < 2
                        and not self._is_our_turn()
                    ):
                        await self.li.abort_game(self.id)
                        break

            print("Quitting engine.")
            await self.engine.quit()
        except Exception as e:
            print(e)
