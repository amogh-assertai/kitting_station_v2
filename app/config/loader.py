"""
Config loader.

Merges config.yaml (non-secret runtime config) and .env (secrets/env-specific
values) into a single settings dict exposed to the Flask app.

Nothing in application code should hardcode config values - everything
configurable should be pulled through this loader.
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Project root = two levels up from this file (app/config/loader.py -> project root)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_YAML_PATH = BASE_DIR / "config.yaml"
ENV_PATH = BASE_DIR / ".env"


def load_settings() -> dict:
    """
    Load and merge config.yaml + .env into a single settings dict.

    Returns a nested dict mirroring config.yaml's structure, with an
    additional top-level "secrets" key holding values loaded from .env.
    """
    # Load .env into process environment
    load_dotenv(dotenv_path=ENV_PATH)

    if not CONFIG_YAML_PATH.exists():
        raise FileNotFoundError(
            f"config.yaml not found at {CONFIG_YAML_PATH}. "
            "This file is required for the application to start."
        )

    with open(CONFIG_YAML_PATH, "r") as f:
        settings = yaml.safe_load(f) or {}

    # Secrets / environment-specific values pulled from .env
    settings["secrets"] = {
        "secret_key": os.environ.get("SECRET_KEY", ""),
        "flask_env": os.environ.get("FLASK_ENV", "production"),
        "mongo_uri": os.environ.get("MONGO_URI", ""),
    }

    _validate_settings(settings)

    return settings


def _validate_settings(settings: dict) -> None:
    """Fail fast if required config is missing, rather than failing
    obscurely later at request time."""
    required_paths = [
        ("app", "name"),
        ("app", "version"),
        ("app", "host"),
        ("app", "port"),
        ("client", "name"),
        ("client", "brand"),
        ("client", "logo_path"),
        ("developer", "name"),
        ("storage", "pqpr_dir"),
        ("storage", "pqpr_allowed_extensions"),
        ("storage", "max_upload_size_mb"),
        ("storage", "audio_dir"),
        ("storage", "audio_allowed_extensions"),
        ("mongodb", "db_name"),
        ("mongodb", "collections", "current_kits"),
        ("mongodb", "collections", "table_configuration"),
        ("mongodb", "collections", "live_activities"),
        ("pqpr_parsing", "sheet_name"),
        ("pqpr_parsing", "header_row"),
        ("pqpr_parsing", "kit_name_column"),
        ("pqpr_parsing", "edp_column"),
        ("pqpr_parsing", "component_start_column"),
        ("pqpr_parsing", "top10_row_count"),
        ("configuration", "tables"),
        ("theme", "default"),
        ("theme", "cookie_name"),
        ("theme", "cookie_max_age_days"),
    ]
    for path in required_paths:
        node = settings
        for key in path:
            if not isinstance(node, dict) or key not in node:
                raise ValueError(
                    f"Missing required config key: {'.'.join(path)} in config.yaml"
                )
            node = node[key]

    if settings["theme"]["default"] not in ("dark", "light"):
        raise ValueError("theme.default in config.yaml must be 'dark' or 'light'")

    _validate_table_registry(settings["configuration"]["tables"])

    if not settings["secrets"]["secret_key"]:
        raise ValueError(
            "SECRET_KEY is not set. Copy .env.example to .env and set a value."
        )

    if not settings["secrets"]["mongo_uri"]:
        raise ValueError(
            "MONGO_URI is not set. Add it to .env (e.g. mongodb://localhost:27017/)."
        )


def _validate_table_registry(tables) -> None:
    """Fail fast on a malformed configuration.tables entry - this list
    drives the whole Configuration section (landing page, table_id
    routing, Mongo document scoping), so a bad entry here should surface
    at startup, not as a KeyError/TypeError deep in a request."""
    if not isinstance(tables, list) or not tables:
        raise ValueError(
            "configuration.tables in config.yaml must be a non-empty list."
        )

    seen_ids = set()
    for entry in tables:
        if not isinstance(entry, dict):
            raise ValueError(
                f"configuration.tables entry must be a mapping, got: {entry!r}"
            )

        for field in ("id", "name", "built"):
            if field not in entry:
                raise ValueError(
                    f"configuration.tables entry missing required key '{field}': {entry!r}"
                )

        table_id = entry["id"]
        if not isinstance(table_id, int) or isinstance(table_id, bool) or table_id <= 0:
            raise ValueError(
                f"configuration.tables entry 'id' must be a positive integer, got: {table_id!r}"
            )
        if table_id in seen_ids:
            raise ValueError(f"configuration.tables has a duplicate id: {table_id}")
        seen_ids.add(table_id)

        if not isinstance(entry["name"], str) or not entry["name"].strip():
            raise ValueError(
                f"configuration.tables entry {table_id} 'name' must be a non-empty string."
            )

        if not isinstance(entry["built"], bool):
            raise ValueError(
                f"configuration.tables entry {table_id} 'built' must be true or false."
            )
