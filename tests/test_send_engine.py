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


class ChannelPrivateError(Exception):
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


def test_send_engine_retryable_permission_error_recovers() -> None:
    clock = FakeClock(datetime(2026, 2, 24, 18, 59, 59, tzinfo=timezone.utc))
    fake_client = FakeClient(
        outcomes=[
            ChatWriteForbiddenError("grupo fechado"),
            ChatWriteForbiddenError("grupo fechado"),
            {"id": 1},
        ]
    )
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
    assert result.status == RunStatus.SUCCESS
    assert result.attempts_count == 3


def test_send_engine_retryable_permission_error_exhausts_window() -> None:
    clock = FakeClock(datetime(2026, 2, 24, 18, 59, 59, tzinfo=timezone.utc))
    fake_client = FakeClient(outcomes=[ChatWriteForbiddenError("grupo fechado")] * 200)
    config = RunConfig(
        profile_id="1",
        group_id=123,
        message_text="Katia x Rodolfo",
        target_time_local="19:00:00",
        warmup_seconds=0,
        retry_min_ms=50,
        retry_max_ms=50,
        max_attempt_window_sec=1,
    )
    result = _run(config, fake_client, clock)
    assert result.status == RunStatus.PERMISSION_ERROR
    assert result.attempts_count > 1


def test_send_engine_permission_error_terminal() -> None:
    clock = FakeClock(datetime(2026, 2, 24, 18, 59, 59, tzinfo=timezone.utc))
    fake_client = FakeClient(outcomes=[ChannelPrivateError("sem permissao")])
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


def _run_with_callback(
    config: RunConfig,
    fake_client: FakeClient,
    clock: FakeClock,
    status_messages: list[str],
):
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
            status_callback=lambda msg: status_messages.append(msg),
        )
    )


def test_race_mode_uses_fixed_retry_ms() -> None:
    clock = FakeClock(datetime(2026, 2, 24, 18, 59, 59, tzinfo=timezone.utc))
    sleep_durations: list[float] = []
    original_sleep = clock.sleep

    async def tracking_sleep(seconds: float) -> None:
        sleep_durations.append(seconds)
        await original_sleep(seconds)

    fake_client = FakeClient(
        outcomes=[ChatWriteForbiddenError("fechado")] * 3 + [{"id": 1}]
    )
    config = RunConfig(
        profile_id="1",
        group_id=123,
        message_text="msg",
        target_time_local="19:00:00",
        warmup_seconds=0,
        retry_min_ms=50,
        retry_max_ms=100,
        max_attempt_window_sec=5,
        race_mode=True,
        race_retry_ms=5,
    )
    engine = SendEngine(
        client_factory=lambda s, a, h: fake_client,
        now_provider=clock.now,
        sleep_callable=tracking_sleep,
        uniform_callable=lambda min_ms, max_ms: float(min_ms),
    )
    result = asyncio.run(
        engine.run(run_config=config, session_string="d", api_id=1, api_hash="h")
    )
    assert result.status == RunStatus.SUCCESS
    assert result.attempts_count == 4
    retry_sleeps = [d for d in sleep_durations if abs(d - 0.005) < 0.001]
    assert len(retry_sleeps) == 3


def test_race_mode_pre_fire_starts_early() -> None:
    clock = FakeClock(datetime(2026, 2, 24, 18, 59, 57, tzinfo=timezone.utc))
    fake_client = FakeClient(outcomes=[{"id": 1}])
    config = RunConfig(
        profile_id="1",
        group_id=123,
        message_text="msg",
        target_time_local="19:00:00",
        warmup_seconds=5,
        max_attempt_window_sec=10,
        race_mode=True,
        pre_fire_seconds=2,
        race_retry_ms=5,
    )
    result = _run(config, fake_client, clock)
    assert result.status == RunStatus.SUCCESS
    assert result.first_attempt_at is not None
    target = datetime(2026, 2, 24, 19, 0, 0, tzinfo=timezone.utc)
    assert result.first_attempt_at < target


def test_race_mode_status_throttle() -> None:
    clock = FakeClock(datetime(2026, 2, 24, 18, 59, 59, tzinfo=timezone.utc))
    fake_client = FakeClient(
        outcomes=[ChatWriteForbiddenError("fechado")] * 100 + [{"id": 1}]
    )
    status_messages: list[str] = []
    config = RunConfig(
        profile_id="1",
        group_id=123,
        message_text="msg",
        target_time_local="19:00:00",
        warmup_seconds=0,
        max_attempt_window_sec=5,
        race_mode=True,
        race_retry_ms=5,
        status_throttle_ms=200,
    )
    result = _run_with_callback(config, fake_client, clock, status_messages)
    assert result.status == RunStatus.SUCCESS
    race_messages = [m for m in status_messages if "Corrida: tentativa" in m]
    assert len(race_messages) < 20


def test_race_mode_false_preserves_original_behavior() -> None:
    clock = FakeClock(datetime(2026, 2, 24, 18, 59, 59, tzinfo=timezone.utc))
    fake_client = FakeClient(
        outcomes=[ChatWriteForbiddenError("fechado"), {"id": 1}]
    )
    config = RunConfig(
        profile_id="1",
        group_id=123,
        message_text="msg",
        target_time_local="19:00:00",
        warmup_seconds=0,
        retry_min_ms=50,
        retry_max_ms=50,
        max_attempt_window_sec=5,
        race_mode=False,
        race_retry_ms=5,
    )
    result = _run(config, fake_client, clock)
    assert result.status == RunStatus.SUCCESS
    assert result.attempts_count == 2
