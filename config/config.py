import configparser
import os
from pathlib import Path


_MODE = os.getenv("MODE", "Debug")
_CONFIG_PATH = Path(__file__).with_name("config.ini")
_config = configparser.ConfigParser()
_config.read(_CONFIG_PATH, encoding="utf-8")


def getconf(option: str) -> str:
    return _config.get(_MODE, option)


def getconf_int(option: str, fallback: int | None = None) -> int:
    if fallback is None:
        return _config.getint(_MODE, option)
    return _config.getint(_MODE, option, fallback=fallback)


def reset_config(filepath: str) -> None:
    _config.read(filepath, encoding="utf-8")
