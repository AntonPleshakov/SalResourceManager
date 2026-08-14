import configparser
import os
from pathlib import Path


_MODE = os.getenv("MODE", "Debug")
_CONFIG_PATH = Path(__file__).with_name("config.ini")
_config = configparser.ConfigParser()
_config.read(_CONFIG_PATH, encoding="utf-8")


def getconf(option: str) -> str:
    return _config.get(_MODE, option)


def reset_config(filepath: str) -> None:
    _config.read(filepath, encoding="utf-8")
