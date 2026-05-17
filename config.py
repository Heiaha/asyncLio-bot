import logging
import os

import yaml
from pydantic import BaseModel, Field, model_validator

from enums import BookSelection, ChallengeMode, ChallengeOpponent, Speed, Variant

logger = logging.getLogger(__name__)


class EngineConfig(BaseModel):
    path: str
    ponder: bool = False
    uci_options: dict[str, int | str | bool] = Field(default_factory=dict)


class BooksConfig(BaseModel):
    enabled: bool = False
    selection: BookSelection = BookSelection.WEIGHTED_RANDOM
    depth: int = 10
    # variant name (Variant.value) -> ordered list of polyglot book paths
    by_variant: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def collect_variant_keys(cls, data):
        # YAML carries variant keys as siblings of enabled/selection/depth;
        # gather them into by_variant so the model itself stays explicit.
        if not isinstance(data, dict):
            return data
        known = {"enabled", "selection", "depth", "by_variant"}
        by_variant = dict(data.get("by_variant") or {})
        for key in list(data):
            if key not in known:
                by_variant[key] = data.pop(key)
        data["by_variant"] = by_variant
        return data

    def for_variant(self, variant: Variant) -> list[str]:
        return self.by_variant.get(variant.value, [])


class RatingDiffs(BaseModel):
    human: int = 4000
    bot: int = 4000


class ChallengeConfig(BaseModel):
    enabled: bool = False
    max_increment: int = 180
    min_increment: int = 0
    max_initial: int = 315360000
    min_initial: int = 0
    variants: list[Variant] = Field(default_factory=list)
    time_controls: list[Speed] = Field(default_factory=list)
    modes: list[ChallengeMode] = Field(default_factory=list)
    opponents: list[ChallengeOpponent] = Field(default_factory=list)
    max_rating_diffs: RatingDiffs = Field(default_factory=RatingDiffs)


class DrawConfig(BaseModel):
    enabled: bool = False
    score: int = 0
    moves: int = 5
    min_game_length: int = 35


class ResignConfig(BaseModel):
    enabled: bool = False
    score: int = -1000
    moves: int = 5


class MatchmakingConfig(BaseModel):
    enabled: bool = False
    variant: Variant = Variant.STANDARD
    initial_times: list[int] = Field(default_factory=list)
    increments: list[int] = Field(default_factory=list)
    max_rating_diff: int = 4000
    min_games: int = 0
    timeout: int = 1
    rated: bool = False


class Config(BaseModel):
    token: str
    concurrency: int = 1
    abort_time: int = 20
    move_overhead: int = 0
    engine: EngineConfig
    books: BooksConfig = Field(default_factory=BooksConfig)
    challenge: ChallengeConfig = Field(default_factory=ChallengeConfig)
    draw: DrawConfig = Field(default_factory=DrawConfig)
    resign: ResignConfig = Field(default_factory=ResignConfig)
    matchmaking: MatchmakingConfig = Field(default_factory=MatchmakingConfig)


# Stable singleton — mutated in place by load_config so `from config import CONFIG`
# keeps working. Fields are unset until load_config runs, so accessing them
# before then raises AttributeError (which is what we want).
CONFIG: Config = Config.model_construct()


def load_config(filename: str) -> None:
    with open(filename, "r") as config_file:
        try:
            data = yaml.safe_load(config_file)
        except Exception as e:
            logger.critical("There is a problem with your config.yml file.")
            raise e
    data["token"] = os.getenv("LICHESS_TOKEN")

    CONFIG.__dict__.update(Config.model_validate(data).__dict__)