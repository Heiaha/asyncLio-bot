from enum import Enum


class GameStatus(Enum):
    CREATED = "created"
    STARTED = "started"
    ABORTED = "aborted"
    MATE = "mate"
    RESIGN = "resign"
    STALEMATE = "stalemate"
    TIMEOUT = "timeout"
    DRAW = "draw"
    OUT_OF_TIME = "outoftime"
    CHEAT = "cheat"
    NO_START = "noStart"
    UNKNOWN_FINISH = "unknownFinish"
    VARIANT_END = "variantEnd"


class Event(Enum):
    PING = "ping"
    CHALLENGE = "challenge"
    CHALLENGE_CANCELED = "challengeCanceled"
    CHALLENGE_DECLINED = "challengeDeclined"
    GAME_START = "gameStart"
    GAME_FINISH = "gameFinish"


class GameEvent(Enum):
    PING = "ping"
    GAME_FULL = "gameFull"
    GAME_STATE = "gameState"
    CHAT_LINE = "chatLine"


class Variant(Enum):
    STANDARD = "standard"
    FROM_POSITION = "fromPosition"
    ANTICHESS = "antichess"
    ATOMIC = "atomic"
    CHESS960 = "chess960"
    CRAZYHOUSE = "crazyhouse"
    HORDE = "horde"
    KING_OF_THE_HILL = "kingOfTheHill"
    RACING_KINGS = "racingKings"
    THREE_CHECK = "threeCheck"


class PerfType(Enum):
    BULLET = "bullet"
    BLITZ = "blitz"
    RAPID = "rapid"
    CLASSICAL = "classical"
    ANTICHESS = "antichess"
    ATOMIC = "atomic"
    CHESS960 = "chess960"
    CRAZYHOUSE = "crazyhouse"
    HORDE = "horde"
    KING_OF_THE_HILL = "kingOfTheHill"
    RACING_KINGS = "racingKings"
    THREE_CHECK = "threeCheck"

    @classmethod
    def from_standard_tc(cls, tc_seconds: int, tc_increment: int = 0) -> "PerfType":
        duration = tc_seconds + 40 * tc_increment
        if duration < 179:
            return cls.BULLET

        if duration < 479:
            return cls.BLITZ

        if duration < 1499:
            return cls.RAPID

        return cls.CLASSICAL

    @classmethod
    def from_nonstandard_variant(cls, variant: Variant) -> "PerfType":
        if variant in (Variant.STANDARD, Variant.FROM_POSITION):
            raise ValueError(f"{variant} not supported as a performance type.")
        return cls(variant.value)
