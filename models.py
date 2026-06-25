from typing import Annotated, Literal, Union

from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
)

from enums import Event, GameEvent, GameStatus, Speed, Variant


class LichessModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# /api/account
class Account(LichessModel):
    username: str
    title: str = ""


# 429 rate-limit error body (e.g. the bot.vsBot.day daily cap)
class RateLimit(LichessModel):
    seconds: float | None = Field(
        default=None, validation_alias=AliasPath("ratelimit", "seconds")
    )


class TimeControl(LichessModel):
    limit: int = 0
    increment: int = 0


# Event stream (/api/stream/event)
class GameEventInfo(LichessModel):
    id: str = Field(validation_alias=AliasChoices("id", "gameId"))
    color: Literal["white", "black"]
    fen: str
    variant: Variant = Field(validation_alias=AliasPath("variant", "key"))
    status: GameStatus = Field(validation_alias=AliasPath("status", "name"))
    opponent: str = Field(validation_alias=AliasPath("opponent", "username"))


class GameStartEvent(LichessModel):
    type: Literal[Event.GAME_START] = Event.GAME_START
    game: GameEventInfo


class GameFinishEvent(LichessModel):
    type: Literal[Event.GAME_FINISH] = Event.GAME_FINISH
    game: GameEventInfo


class ChallengePlayer(LichessModel):
    name: str | None = None
    title: str | None = None
    rating: int | None = None


class ChallengeInfo(LichessModel):
    id: str
    rated: bool
    speed: Speed
    variant: Variant = Field(validation_alias=AliasPath("variant", "key"))
    challenger: ChallengePlayer | None = None
    dest_user: ChallengePlayer | None = Field(default=None, alias="destUser")
    time_control: TimeControl = Field(alias="timeControl")


class ChallengeEvent(LichessModel):
    type: Literal[Event.CHALLENGE] = Event.CHALLENGE
    challenge: ChallengeInfo


class ChallengeCanceledEvent(LichessModel):
    type: Literal[Event.CHALLENGE_CANCELED] = Event.CHALLENGE_CANCELED
    challenge: ChallengeInfo


class PingEvent(LichessModel):
    type: Literal[Event.PING] = Event.PING


class UnknownEvent(LichessModel):
    type: Literal[Event.UNKNOWN] = Event.UNKNOWN


StreamEvent = Annotated[
    Union[
        GameStartEvent,
        GameFinishEvent,
        ChallengeEvent,
        ChallengeCanceledEvent,
        PingEvent,
        UnknownEvent,
    ],
    Field(discriminator="type"),
]

stream_event_adapter = TypeAdapter(StreamEvent)


def parse_event(raw: str | bytes) -> StreamEvent:
    # Lichess sends events we don't model (e.g. challengeDeclined); fall back to
    # UnknownEvent so an unmodeled type doesn't crash the stream.
    try:
        return stream_event_adapter.validate_json(raw)
    except ValidationError:
        return UnknownEvent()


# Game stream (/api/bot/game/stream/{game_id})
class GameState(LichessModel):
    type: Literal[GameEvent.GAME_STATE] = GameEvent.GAME_STATE
    moves: str
    wtime: int
    btime: int
    winc: int
    binc: int
    status: GameStatus
    winner: str | None = None


class GameFull(LichessModel):
    type: Literal[GameEvent.GAME_FULL] = GameEvent.GAME_FULL
    state: GameState


class OpponentGone(LichessModel):
    type: Literal[GameEvent.OPPONENT_GONE] = GameEvent.OPPONENT_GONE
    claim_win_in_seconds: int | None = Field(
        default=None, alias="claimWinInSeconds"
    )


class GamePing(LichessModel):
    type: Literal[GameEvent.PING] = GameEvent.PING


class GameUnknown(LichessModel):
    type: Literal[GameEvent.UNKNOWN] = GameEvent.UNKNOWN


GameStreamEvent = Annotated[
    Union[GameFull, GameState, OpponentGone, GamePing, GameUnknown],
    Field(discriminator="type"),
]

game_stream_adapter = TypeAdapter(GameStreamEvent)


def parse_game_event(raw: str | bytes) -> GameStreamEvent:
    # Mirror parse_event: route any unmodeled game-stream type to GameUnknown
    # rather than failing validation.
    try:
        return game_stream_adapter.validate_json(raw)
    except ValidationError:
        return GameUnknown()


# /api/bot/online
class PerfInfo(LichessModel):
    rating: int = 1500
    games: int = 0


class OnlineBot(LichessModel):
    username: str
    disabled: bool = False
    tos_violation: bool = Field(default=False, alias="tosViolation")
    perfs: dict[str, PerfInfo] = Field(default_factory=dict)