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

