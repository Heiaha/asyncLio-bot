import logging
import os

import yaml

logger = logging.getLogger(__name__)

CONFIG = {}


def load_config(filename: str):
    with open(filename, "r") as config_file:
        try:
            config = yaml.safe_load(config_file)
        except Exception as e:
            logger.critical("There is a problem with your config.yml file.")
            raise e
    if "LICHESS_BOT_TOKEN" in os.environ:
        config["token"] = os.environ["LICHESS_BOT_TOKEN"]

    global CONFIG
    CONFIG.clear()
    CONFIG.update(config)
