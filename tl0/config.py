"""Configuration loading and path resolution for tl0."""

import json
import os
from pathlib import Path

_CONFIG_FILENAME = "tl0.json"
_ENV_VAR = "TL0_TASKS_DIR"
_DEFAULT_TASKS_DIR = Path.home() / "tl0-tasks"


def find_config_file(start: Path | None = None) -> Path | None:
    """Walk up from *start* (default: cwd) looking for tl0.json."""
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / _CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_config(start: Path | None = None) -> dict:
    """Load the nearest tl0.json, or return an empty dict."""
    path = find_config_file(start)
    if path is None:
        return {}
    with open(path) as f:
        return json.load(f)


def resolve_tasks_dir(config: dict | None = None) -> Path:
    """Determine the tasks directory.

    Priority:
      1. TL0_TASKS_DIR environment variable
      2. tasks_dir from tl0.json
      3. ~/tl0-tasks (default)
    """
    env = os.environ.get(_ENV_VAR)
    if env:
        return Path(env).expanduser().resolve()

    if config is None:
        config = load_config()

    if "tasks_dir" in config:
        return Path(config["tasks_dir"]).expanduser().resolve()

    return _DEFAULT_TASKS_DIR


def resolve_project_name(config: dict | None = None) -> str:
    """Get the project name from config, or default to 'tl0'."""
    if config is None:
        config = load_config()
    return config.get("project_name", "tl0")
