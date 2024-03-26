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
    OPPONENT_GONE = "opponentGone"


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
        challenge_config = CONFIG["challenge"]
        if not challenge_config["enabled"]:
            return cls.GENERIC

        allowed_modes = challenge_config["modes"]
        allowed_opponents = challenge_config["opponents"]
        allowed_variants = challenge_config["variants"]
        allowed_tcs = challenge_config["time_controls"]
        min_increment = challenge_config.get("min_increment", 0)
        max_increment = challenge_config.get("max_increment", 180)
        min_initial = challenge_config.get("min_initial", 0)
        max_initial = challenge_config.get("max_initial", 315360000)
        max_bot_rating_diff = challenge_config["max_rating_diffs"].get("bot", 4000)
        max_human_rating_diff = challenge_config["max_rating_diffs"].get("human", 4000)

        challenge_info = event["challenge"]
        is_rated = challenge_info["rated"]
        if is_rated and "rated" not in allowed_modes:
            return cls.CASUAL

        if not is_rated and "casual" not in allowed_modes:
            return cls.RATED

        variant = challenge_info["variant"]["key"]
        if variant not in allowed_variants:
            return cls.VARIANT

        if challenger_info := challenge_info["challenger"]:
            is_bot = challenger_info["title"] == "BOT"
            their_rating = challenger_info.get("rating")
        else:
            is_bot = False
            their_rating = None

        if my_info := challenge_info["destUser"]:
            my_rating = my_info.get("rating")
        else:
            my_rating = None

        if is_bot and "bot" not in allowed_opponents:
            return cls.NO_BOT

        if not is_bot and "human" not in allowed_opponents:
            return cls.ONLY_BOT

        increment = challenge_info["timeControl"].get("increment", 0)
        initial = challenge_info["timeControl"].get("limit", 0)
        speed = challenge_info["speed"]
        if speed not in allowed_tcs:
            return cls.TIME_CONTROL

        if initial < min_initial or increment < min_increment:
            return cls.TOO_FAST

        if initial > max_initial or increment > max_increment:
            return cls.TOO_SLOW

        if is_rated and my_rating is not None and their_rating is not None:
            rating_diff = abs(my_rating - their_rating)
            if is_bot and rating_diff > max_bot_rating_diff:
                return cls.GENERIC

            if not is_bot and rating_diff > max_human_rating_diff:
                return cls.GENERIC
