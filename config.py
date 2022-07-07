import yaml

with open("config.yml", "r") as config_file:
    CONFIG = yaml.safe_load(config_file)
