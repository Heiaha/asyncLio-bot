import logging
import os
from typing import get_origin

import yaml
from pydantic import BaseModel, Field, model_validator

from enums import BookSelection, ChallengeMode, ChallengeOpponent, Speed, Variant

logger = logging.getLogger(__name__)


class ConfigModel(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def empty_when_null(cls, data):
        # A YAML key written with all of its entries commented out (e.g. `users:`)
        # parses to None instead of being absent, so default_factory never fires.
        # Treat a null list/dict field as empty so commenting everything out under a
        # key doesn't crash config loading.
        if not isinstance(data, dict):
            return data
        for name, field in cls.model_fields.items():
            if data.get(name) is None and name in data:
                origin = get_origin(field.annotation)
                if origin is list:
                    data[name] = []
                elif origin is dict:
                    data[name] = {}
        return data


class EngineConfig(ConfigModel):
    path: str
    ponder: bool = False
    uci_options: dict[str, int | str | bool] = Field(default_factory=dict)


class BooksConfig(ConfigModel):
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


class RatingDiffs(ConfigModel):
    human: int = 4000
    bot: int = 4000


class ChallengeConfig(ConfigModel):
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


class DrawConfig(ConfigModel):
    enabled: bool = False
    score: int = 0
    moves: int = 5
    min_game_length: int = 35


class ResignConfig(ConfigModel):
    enabled: bool = False
    score: int = -1000
    moves: int = 5


class MatchmakingConfig(ConfigModel):
    enabled: bool = False
    variant: Variant = Variant.STANDARD
    initial_times: list[int] = Field(default_factory=list)
    increments: list[int] = Field(default_factory=list)
    max_rating_diff: int = 4000
    min_games: int = 0
    timeout: int = 1
    rated: bool = False


class BlocklistConfig(ConfigModel):
    users: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    refresh: int = 0


class Config(ConfigModel):
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
    blocklist: BlocklistConfig = Field(default_factory=BlocklistConfig)


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
