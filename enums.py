import re
from enum import StrEnum


class GameStatus(StrEnum):
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
    INSUFFICIENT_MATERIAL_CLAIM = "insufficientMaterialClaim"
    VARIANT_END = "variantEnd"
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value):
        return cls.UNKNOWN


class Event(StrEnum):
    PING = "ping"
    CHALLENGE = "challenge"
    CHALLENGE_CANCELED = "challengeCanceled"
    CHALLENGE_DECLINED = "challengeDeclined"
    GAME_START = "gameStart"
    GAME_FINISH = "gameFinish"
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value):
        return cls.UNKNOWN


class GameEvent(StrEnum):
    PING = "ping"
    GAME_FULL = "gameFull"
    GAME_STATE = "gameState"
    CHAT_LINE = "chatLine"
    OPPONENT_GONE = "opponentGone"
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value):
        return cls.UNKNOWN


class Variant(StrEnum):
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

    def __str__(self):
        return re.sub("([A-Z])", r" \1", self.value).title()


class PerfType(StrEnum):
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

    def __str__(self):
        return re.sub("([A-Z])", r" \1", self.value).title()

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
        return cls(variant)


class BookSelection(StrEnum):
    WEIGHTED_RANDOM = "weighted_random"
    UNIFORM_RANDOM = "uniform_random"
    BEST_MOVE = "best_move"


class DeclineReason(StrEnum):
    GENERIC = "generic"
    LATER = "later"
    TOO_FAST = "tooFast"
    TOO_SLOW = "tooSlow"
    TIME_CONTROL = "timeControl"
    RATED = "rated"
    CASUAL = "casual"
    STANDARD = "standard"
    VARIANT = "variant"
    NO_BOT = "noBot"
    ONLY_BOT = "onlyBot"

    def __str__(self):
        return re.sub("([A-Z])", r" \1", self.value).lower()
