from datetime import datetime, timedelta, timezone

from telegram_sender.time_engine import compute_target_datetime, compute_warmup_datetime, format_countdown


def test_compute_target_datetime_same_day() -> None:
    now = datetime(2026, 2, 24, 18, 30, 0, tzinfo=timezone.utc)
    target = compute_target_datetime("19:00:00", now)
    assert target == datetime(2026, 2, 24, 19, 0, 0, tzinfo=timezone.utc)


def test_compute_target_datetime_next_day_when_past() -> None:
    now = datetime(2026, 2, 24, 19, 30, 0, tzinfo=timezone.utc)
    target = compute_target_datetime("19:00:00", now)
    assert target == datetime(2026, 2, 25, 19, 0, 0, tzinfo=timezone.utc)


def test_compute_target_datetime_respects_rollover_grace() -> None:
    now = datetime(2026, 2, 24, 19, 0, 4, tzinfo=timezone.utc)
    target = compute_target_datetime("19:00:00", now, rollover_grace_seconds=10)
    assert target == datetime(2026, 2, 24, 19, 0, 0, tzinfo=timezone.utc)


def test_compute_warmup_datetime() -> None:
    target = datetime(2026, 2, 24, 19, 0, 0, tzinfo=timezone.utc)
    warmup = compute_warmup_datetime(target, 60)
    assert warmup == datetime(2026, 2, 24, 18, 59, 0, tzinfo=timezone.utc)


def test_format_countdown() -> None:
    assert format_countdown(timedelta(seconds=3661)) == "01:01:01"
