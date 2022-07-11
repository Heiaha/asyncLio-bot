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


class Speed(Enum):
    BULLET = "bullet"
    BLITZ = "blitz"
    RAPID = "rapid"
    CLASSICAL = "classical"

    @classmethod
    def from_tc(cls, tc_seconds: int, tc_increment: int = 0):
        duration = tc_seconds + 40 * tc_increment
        if duration < 179:
            return cls.BULLET

        if duration < 479:
            return cls.BLITZ

        if duration < 1499:
            return cls.RAPID

        return cls.CLASSICAL
