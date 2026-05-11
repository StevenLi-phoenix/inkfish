"""Unit tests for inkfish.config (M0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from inkfish.config import Settings, SimConfig, load_config  # noqa: E402


class TestLoadConfigReturnsSettingsAndSimConfig:
    """load_config returns correctly typed objects with expected field values."""

    def test_returns_tuple_of_correct_types(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key-for-unit-tests")
        settings, sim_cfg = load_config(repo_root / "inkfish.toml")
        assert isinstance(settings, Settings)
        assert isinstance(sim_cfg, SimConfig)

    def test_simconfig_model_from_toml(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key-for-unit-tests")
        _, sim_cfg = load_config(repo_root / "inkfish.toml")
        assert sim_cfg.model == "deepseek-v4-pro"

    def test_simconfig_llm_fields_from_toml(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key-for-unit-tests")
        _, sim_cfg = load_config(repo_root / "inkfish.toml")
        assert sim_cfg.max_retries == 3
        assert sim_cfg.temperature == pytest.approx(0.7)
        assert sim_cfg.max_tokens == 16384  # v4-pro reasoning + tool args budget
        assert sim_cfg.log_level == "INFO"

    def test_simconfig_simulation_fields_from_toml(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key-for-unit-tests")
        _, sim_cfg = load_config(repo_root / "inkfish.toml")
        assert sim_cfg.tick_interval_hours == 1
        assert sim_cfg.max_concurrent_llm_calls == 1

    def test_settings_db_url_from_toml(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key-for-unit-tests")
        settings, _ = load_config(repo_root / "inkfish.toml")
        assert "inkfish.db" in settings.db_url

    def test_settings_api_key_is_secret_str(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key-for-unit-tests")
        settings, _ = load_config(repo_root / "inkfish.toml")
        # SecretStr value must not leak in repr/str
        assert "sk-test-key-for-unit-tests" not in repr(settings)
        # But the actual value is accessible via get_secret_value()
        assert settings.deepseek_api_key.get_secret_value() == "sk-test-key-for-unit-tests"


class TestSimConfigDefaultsWhenTomlSectionMissing:
    """SimConfig falls back to dataclass defaults for missing toml sections."""

    def test_minimal_toml_gives_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        minimal_toml = tmp_path / "minimal.toml"
        minimal_toml.write_text("[simulation]\ntick_interval_hours = 1\n")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-minimal-test")
        _, sim_cfg = load_config(minimal_toml)
        # Fields not in toml should be dataclass defaults
        assert sim_cfg.max_retries == SimConfig.max_retries
        assert sim_cfg.temperature == pytest.approx(SimConfig.temperature)
        assert sim_cfg.max_tokens == SimConfig.max_tokens
        assert sim_cfg.min_weight == pytest.approx(SimConfig.min_weight)
        assert sim_cfg.interaction_max_limit == SimConfig.interaction_max_limit

    def test_empty_toml_gives_all_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty_toml = tmp_path / "empty.toml"
        empty_toml.write_text("")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-empty-test")
        _, sim_cfg = load_config(empty_toml)
        assert sim_cfg.model == SimConfig.model
        assert sim_cfg.tick_interval_hours == SimConfig.tick_interval_hours
        assert sim_cfg.directors_count == SimConfig.directors_count

    def test_missing_toml_gives_all_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nonexistent = tmp_path / "does_not_exist.toml"
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-missing-test")
        _, sim_cfg = load_config(nonexistent)
        assert sim_cfg.model == SimConfig.model


class TestSettingsLoadsFromEnvFile:
    """Settings reads DEEPSEEK_API_KEY from a .env file via pydantic-settings."""

    def test_loads_from_dotenv_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("DEEPSEEK_API_KEY=sk-from-dotenv-file\n")
        # Remove any real env var so the .env file value wins
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        settings = Settings(_env_file=str(env_file))  # type: ignore[call-arg]
        assert settings.deepseek_api_key.get_secret_value() == "sk-from-dotenv-file"

    def test_env_var_overrides_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("DEEPSEEK_API_KEY=sk-from-file\n")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env-var")
        # env var takes precedence over .env file in pydantic-settings
        settings = Settings(_env_file=str(env_file))  # type: ignore[call-arg]
        assert settings.deepseek_api_key.get_secret_value() == "sk-from-env-var"

    def test_db_url_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-db-test")
        settings = Settings()
        assert settings.db_url == "sqlite:///data/inkfish.db"
