"""Jinja environment shared by the form answers, documents and suggested answers (templates/)."""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).parent / "templates"


def environment(lib) -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), trim_blocks=True, lstrip_blocks=True)
    env.filters["method_label"] = lambda k: lib["methods"].get(k, {}).get("label", k)
    env.filters["location_label"] = lambda k: lib["locations"].get(k, {}).get("label", k)
    env.filters["instrument_short"] = lambda k: lib["instruments"].get(k, {}).get("name", k).split("(")[-1].rstrip(")")
    return env
