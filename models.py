from typing import Literal, Union

from pydantic import AliasChoices, AliasPath, BaseModel, ConfigDict, Field

from enums import Event, GameEvent, GameStatus, Speed, Variant


class LichessModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# /api/account
class Account(LichessModel):
    username: str
    title: str = ""


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
    type: Event = Event.GAME_START
    game: GameEventInfo


class GameFinishEvent(LichessModel):
    type: Event = Event.GAME_FINISH
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
    type: Event = Event.CHALLENGE
    challenge: ChallengeInfo


class ChallengeCanceledEvent(LichessModel):
    type: Event = Event.CHALLENGE_CANCELED
    challenge: ChallengeInfo


class PingEvent(LichessModel):
    type: Event = Event.PING


class UnknownEvent(LichessModel):
    type: Event = Event.UNKNOWN


StreamEvent = Union[
    GameStartEvent,
    GameFinishEvent,
    ChallengeEvent,
    ChallengeCanceledEvent,
    PingEvent,
    UnknownEvent,
]


def parse_event(raw: dict) -> StreamEvent:
    event_type = Event(raw.get("type", "unknown"))
    if event_type == Event.GAME_START:
        return GameStartEvent.model_validate(raw)
    if event_type == Event.GAME_FINISH:
        return GameFinishEvent.model_validate(raw)
    if event_type == Event.CHALLENGE:
        return ChallengeEvent.model_validate(raw)
    if event_type == Event.CHALLENGE_CANCELED:
        return ChallengeCanceledEvent.model_validate(raw)
    if event_type == Event.PING:
        return PingEvent.model_validate(raw)
    return UnknownEvent.model_validate(raw)


# Game stream (/api/bot/game/stream/{game_id})
class GameState(LichessModel):
    type: GameEvent = GameEvent.GAME_STATE
    moves: str
    wtime: int
    btime: int
    winc: int
    binc: int
    status: GameStatus
    winner: str | None = None


class GameFull(LichessModel):
    type: GameEvent = GameEvent.GAME_FULL
    state: GameState


class OpponentGone(LichessModel):
    type: GameEvent = GameEvent.OPPONENT_GONE
    claim_win_in_seconds: int | None = Field(
        default=None, alias="claimWinInSeconds"
    )


class GamePing(LichessModel):
    type: GameEvent = GameEvent.PING


class GameUnknown(LichessModel):
    type: GameEvent = GameEvent.UNKNOWN


GameStreamEvent = Union[GameFull, GameState, OpponentGone, GamePing, GameUnknown]


def parse_game_event(raw: dict) -> GameStreamEvent:
    event_type = GameEvent(raw.get("type", "unknown"))
    if event_type == GameEvent.GAME_FULL:
        return GameFull.model_validate(raw)
    if event_type == GameEvent.GAME_STATE:
        return GameState.model_validate(raw)
    if event_type == GameEvent.OPPONENT_GONE:
        return OpponentGone.model_validate(raw)
    if event_type == GameEvent.PING:
        return GamePing.model_validate(raw)
    return GameUnknown.model_validate(raw)


# /api/bot/online
class PerfInfo(LichessModel):
    rating: int = 1500
    games: int = 0


class OnlineBot(LichessModel):
    username: str
    disabled: bool = False
    tos_violation: bool = Field(default=False, alias="tosViolation")
    perfs: dict[str, PerfInfo] = Field(default_factory=dict)