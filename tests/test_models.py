import pytest

from telegram_sender.models import RunConfig


def test_run_config_validates_successfully() -> None:
    config = RunConfig(
        profile_id="123",
        group_id=456,
        message_text="Katia x Rodolfo",
        target_time_local="19:00:00",
    )
    config.validate()


def test_run_config_rejects_empty_message() -> None:
    config = RunConfig(
        profile_id="123",
        group_id=456,
        message_text=" ",
        target_time_local="19:00:00",
    )
    with pytest.raises(ValueError, match="message_text"):
        config.validate()


def test_run_config_rejects_invalid_time_format() -> None:
    config = RunConfig(
        profile_id="123",
        group_id=456,
        message_text="ok",
        target_time_local="19:00",
    )
    with pytest.raises(ValueError, match="HH:MM:SS"):
        config.validate()


def test_run_config_validates_race_mode_fields() -> None:
    config = RunConfig(
        profile_id="1",
        group_id=123,
        message_text="msg",
        target_time_local="19:00:00",
        race_mode=True,
        pre_fire_seconds=5,
        race_retry_ms=5,
        status_throttle_ms=500,
        keepalive_interval_sec=15,
    )
    config.validate()


def test_run_config_rejects_negative_pre_fire() -> None:
    config = RunConfig(
        profile_id="1",
        group_id=123,
        message_text="msg",
        target_time_local="19:00:00",
        pre_fire_seconds=-1,
    )
    with pytest.raises(ValueError, match="pre_fire_seconds"):
        config.validate()


def test_run_config_rejects_race_retry_ms_zero() -> None:
    config = RunConfig(
        profile_id="1",
        group_id=123,
        message_text="msg",
        target_time_local="19:00:00",
        race_retry_ms=0,
    )
    with pytest.raises(ValueError, match="race_retry_ms"):
        config.validate()


def test_run_config_rejects_status_throttle_too_low() -> None:
    config = RunConfig(
        profile_id="1",
        group_id=123,
        message_text="msg",
        target_time_local="19:00:00",
        status_throttle_ms=10,
    )
    with pytest.raises(ValueError, match="status_throttle_ms"):
        config.validate()

