import os

import yaml
import logging


logger = logging.getLogger(__name__)


with open("config.yml", "r") as config_file:
    try:
        CONFIG = yaml.safe_load(config_file)
    except Exception as e:
        logger.critical("There is a problem with your config.yml file.")
        raise e
if "LICHESS_BOT_TOKEN" in os.environ:
    CONFIG["token"] = os.environ["LICHESS_BOT_TOKEN"]
