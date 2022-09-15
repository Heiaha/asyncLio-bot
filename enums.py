import re
from enum import Enum

from config import CONFIG


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

    def __str__(self):
        return re.sub("([A-Z])", r" \1", self.value).title()


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
        return cls(variant.value)


class BookSelection(Enum):
    WEIGHTED_RANDOM = "weighted_random"
    UNIFORM_RANDOM = "uniform_random"
    BEST_MOVE = "best_move"


class DeclineReason(Enum):
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

    @classmethod
    def from_event(cls, event: dict) -> "DeclineReason":
        if not CONFIG["challenge"]["enabled"]:
            return cls.GENERIC

        allowed_modes = CONFIG["challenge"]["modes"]
        allowed_opponents = CONFIG["challenge"]["opponents"]
        allowed_variants = CONFIG["challenge"]["variants"]
        allowed_tcs = CONFIG["challenge"]["time_controls"]
        min_increment = CONFIG["challenge"].get("min_increment", 0)
        max_increment = CONFIG["challenge"].get("max_increment", 180)
        min_initial = CONFIG["challenge"].get("min_initial", 0)
        max_initial = CONFIG["challenge"].get("max_initial", 315360000)

        is_rated = event["challenge"]["rated"]
        if is_rated and "rated" not in allowed_modes:
            return cls.CASUAL

        if not is_rated and "casual" not in allowed_modes:
            return cls.RATED

        variant = event["challenge"]["variant"]["key"]
        if variant not in allowed_variants:
            return cls.VARIANT

        is_bot = event["challenge"]["challenger"]["title"] == "BOT"
        if is_bot and "bot" not in allowed_opponents:
            return cls.NO_BOT

        if not is_bot and "human" not in allowed_opponents:
            return cls.ONLY_BOT

        increment = event["challenge"]["timeControl"].get("increment", 0)
        initial = event["challenge"]["timeControl"].get("limit", 0)
        speed = event["challenge"]["speed"]
        if speed not in allowed_tcs:
            return cls.TIME_CONTROL

        if initial < min_initial or increment < min_increment:
            return cls.TOO_FAST

        if initial > max_initial or increment > max_increment:
            return cls.TOO_SLOW
