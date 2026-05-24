import pathlib
from typing import Optional

import yaml

_WEIGHTS_DIR = pathlib.Path(__file__).parent

_cache: dict = {}


def load_weights(name: str) -> dict:
    """Load weights YAML by name (e.g. "tier0", "tier1"). Results are cached."""
    if name in _cache:
        return _cache[name]
    path = _WEIGHTS_DIR / f"{name}.yaml"
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    _cache[name] = data
    return data
