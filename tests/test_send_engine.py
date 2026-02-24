import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from telegram_sender.models import RunConfig, RunStatus
from telegram_sender.send_engine import SendEngine


class FakeClock:
    def __init__(self, current: datetime):
        self.current = current

    def now(self) -> datetime:
        return self.current

    async def sleep(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


class FakeFloodWaitError(Exception):
    def __init__(self, seconds: int):
        super().__init__(f"FloodWait {seconds}s")
        self.seconds = seconds


class ChatWriteForbiddenError(Exception):
    pass


class FakeClient:
    def __init__(self, outcomes: list[Any]):
        self.outcomes = outcomes
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def is_user_authorized(self) -> bool:
        return True

    async def get_entity(self, group_id: int) -> int:
        return group_id

    async def send_message(self, group_entity: int, message_text: str) -> dict[str, int]:
        if not self.outcomes:
            return {"id": 1}
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return {"id": 1}


def _run(config: RunConfig, fake_client: FakeClient, clock: FakeClock):
    engine = SendEngine(
        client_factory=lambda session, api_id, api_hash: fake_client,
        now_provider=clock.now,
        sleep_callable=clock.sleep,
        uniform_callable=lambda min_ms, max_ms: float(min_ms),
    )
    return asyncio.run(
        engine.run(
            run_config=config,
            session_string="dummy",
            api_id=1,
            api_hash="hash",
        )
    )


def test_send_engine_success_on_first_attempt() -> None:
    clock = FakeClock(datetime(2026, 2, 24, 18, 59, 59, tzinfo=timezone.utc))
    fake_client = FakeClient(outcomes=[{"id": 1}])
    config = RunConfig(
        profile_id="1",
        group_id=123,
        message_text="Katia x Rodolfo",
        target_time_local="19:00:00",
        warmup_seconds=0,
        retry_min_ms=50,
        retry_max_ms=50,
        max_attempt_window_sec=300,
    )
    result = _run(config, fake_client, clock)
    assert result.status == RunStatus.SUCCESS
    assert result.attempts_count == 1


def test_send_engine_floodwait_exceeded() -> None:
    clock = FakeClock(datetime(2026, 2, 24, 18, 59, 59, tzinfo=timezone.utc))
    fake_client = FakeClient(outcomes=[FakeFloodWaitError(10)])
    config = RunConfig(
        profile_id="1",
        group_id=123,
        message_text="Katia x Rodolfo",
        target_time_local="19:00:00",
        warmup_seconds=0,
        retry_min_ms=50,
        retry_max_ms=50,
        max_attempt_window_sec=5,
    )
    result = _run(config, fake_client, clock)
    assert result.status == RunStatus.FLOODWAIT_EXCEEDED
    assert result.attempts_count == 1


def test_send_engine_permission_error() -> None:
    clock = FakeClock(datetime(2026, 2, 24, 18, 59, 59, tzinfo=timezone.utc))
    fake_client = FakeClient(outcomes=[ChatWriteForbiddenError("sem permissao")])
    config = RunConfig(
        profile_id="1",
        group_id=123,
        message_text="Katia x Rodolfo",
        target_time_local="19:00:00",
        warmup_seconds=0,
        retry_min_ms=50,
        retry_max_ms=50,
        max_attempt_window_sec=5,
    )
    result = _run(config, fake_client, clock)
    assert result.status == RunStatus.PERMISSION_ERROR
    assert result.attempts_count == 1

