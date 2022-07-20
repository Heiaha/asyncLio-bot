import os
import yaml
from loguru import logger

with open("config.yml", "r") as config_file:
    try:
        CONFIG = yaml.safe_load(config_file)
    except Exception as e:
        logger.error("There is a problem with your config.yml file.")
        raise e
if "LICHESS_BOT_TOKEN" in os.environ:
    CONFIG["token"] = os.environ["LICHESS_BOT_TOKEN"]
