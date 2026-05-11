"""inkfish.config — M0: runtime configuration loader (Settings + SimConfig)."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Secrets and environment-sourced configuration loaded from .env."""

    deepseek_api_key: SecretStr
    db_url: str = "sqlite:///data/inkfish.db"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@dataclass(frozen=True)
class SimConfig:
    """Simulation runtime parameters loaded from inkfish.toml.

    P0-relevant fields are required; P1+ fields have defaults so the toml
    can omit them without errors.
    """

    # [llm]
    model: str = "deepseek-v4-pro"
    max_retries: int = 3
    temperature: float = 0.7
    max_tokens: int = 800
    log_level: str = "INFO"

    # [simulation]
    tick_interval_hours: int = 1
    max_steps: int = 0
    max_concurrent_llm_calls: int = 1

    # [characters]  — P1+ but parsed eagerly to keep toml complete
    min_weight: float = 0.05
    max_updates_per_tick: int = 3
    interaction_max_limit: int = 10
    dpo_sigma: float = 0.1

    # [directors]
    directors_count: int = 1
    pacing_stale_threshold: int = 5

    # [routing]
    default_provider: str = "deepseek"
    default_model: str = "deepseek-v4-pro"

    # [hot_topics]
    hot_topics_enabled: bool = False
    hot_topics_source: str = "manual"
    hot_topics_poll_interval_minutes: int = 60

    # [writer]
    suggested_split_ticks: int = 50

    # unused sentinel to allow future extension without breaking frozen dataclass
    _extra: dict = field(default_factory=dict, compare=False, hash=False)  # type: ignore[assignment]


def load_config(
    toml_path: Path = Path("inkfish.toml"),
) -> tuple[Settings, SimConfig]:
    """Load Settings from environment and SimConfig from *toml_path*.

    Returns:
        A (Settings, SimConfig) pair ready for injection into engine modules.

    Raises:
        FileNotFoundError: if *toml_path* does not exist.
        pydantic.ValidationError: if required env vars are missing.
    """
    raw: dict = {}
    if toml_path.exists():
        with toml_path.open("rb") as fh:
            raw = tomllib.load(fh)
        logger.debug("Loaded config from %s", toml_path)
    else:
        logger.warning("Config file %s not found — using all defaults", toml_path)

    sim_section = raw.get("simulation", {})
    llm_section = raw.get("llm", {})
    char_section = raw.get("characters", {})
    dir_section = raw.get("directors", {})
    routing_section = raw.get("routing", {})
    hot_section = raw.get("hot_topics", {})
    writer_section = raw.get("writer", {})
    storage_section = raw.get("storage", {})

    sim_cfg = SimConfig(
        model=routing_section.get("default_model", SimConfig.model),
        max_retries=llm_section.get("max_retries", SimConfig.max_retries),
        temperature=llm_section.get("temperature", SimConfig.temperature),
        max_tokens=llm_section.get("max_tokens", SimConfig.max_tokens),
        log_level=llm_section.get("log_level", SimConfig.log_level),
        tick_interval_hours=sim_section.get(
            "tick_interval_hours", SimConfig.tick_interval_hours
        ),
        max_steps=sim_section.get("max_steps", SimConfig.max_steps),
        max_concurrent_llm_calls=sim_section.get(
            "max_concurrent_llm_calls", SimConfig.max_concurrent_llm_calls
        ),
        min_weight=char_section.get("min_weight", SimConfig.min_weight),
        max_updates_per_tick=char_section.get(
            "max_updates_per_tick", SimConfig.max_updates_per_tick
        ),
        interaction_max_limit=char_section.get(
            "interaction_max_limit", SimConfig.interaction_max_limit
        ),
        dpo_sigma=char_section.get("dpo_sigma", SimConfig.dpo_sigma),
        directors_count=dir_section.get("count", SimConfig.directors_count),
        pacing_stale_threshold=dir_section.get(
            "pacing_stale_threshold", SimConfig.pacing_stale_threshold
        ),
        default_provider=routing_section.get(
            "default_provider", SimConfig.default_provider
        ),
        default_model=routing_section.get("default_model", SimConfig.default_model),
        hot_topics_enabled=hot_section.get("enabled", SimConfig.hot_topics_enabled),
        hot_topics_source=hot_section.get("source", SimConfig.hot_topics_source),
        hot_topics_poll_interval_minutes=hot_section.get(
            "poll_interval_minutes", SimConfig.hot_topics_poll_interval_minutes
        ),
        suggested_split_ticks=writer_section.get(
            "suggested_split_ticks", SimConfig.suggested_split_ticks
        ),
    )

    # db_url from toml [storage] takes precedence if provided; env var wins at Settings level
    db_url_override = storage_section.get("db_url")
    settings = Settings(
        **({} if db_url_override is None else {"db_url": db_url_override})
    )

    logging.basicConfig(level=sim_cfg.log_level)
    return settings, sim_cfg
