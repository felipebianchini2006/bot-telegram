from __future__ import annotations

from datetime import datetime, timedelta

from telegram_sender.models import ClockCheck

try:
    import ntplib
except ImportError:  # pragma: no cover - covered by runtime dependency
    ntplib = None


def compute_target_datetime(
    target_time_local: str,
    now: datetime | None = None,
    rollover_grace_seconds: int = 0,
) -> datetime:
    current = now or datetime.now().astimezone()
    hour, minute, second = parse_time_string(target_time_local)
    target = current.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if target <= current:
        delta_seconds = (current - target).total_seconds()
        if delta_seconds <= rollover_grace_seconds:
            return target
        target += timedelta(days=1)
    return target


def compute_warmup_datetime(target_datetime: datetime, warmup_seconds: int) -> datetime:
    return target_datetime - timedelta(seconds=warmup_seconds)


def parse_time_string(value: str) -> tuple[int, int, int]:
    try:
        parsed = datetime.strptime(value, "%H:%M:%S")
    except ValueError as error:
        raise ValueError("Horario invalido. Use HH:MM:SS.") from error
    return parsed.hour, parsed.minute, parsed.second


def format_countdown(remaining: timedelta) -> str:
    total_seconds = max(int(remaining.total_seconds()), 0)
    hours, left = divmod(total_seconds, 3600)
    minutes, seconds = divmod(left, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def timezone_summary() -> tuple[str, str, bool]:
    now = datetime.now().astimezone()
    tz_name = str(now.tzinfo)
    offset = now.utcoffset() or timedelta(0)
    offset_sign = "+" if offset.total_seconds() >= 0 else "-"
    offset_abs = abs(int(offset.total_seconds()))
    hours, left = divmod(offset_abs, 3600)
    minutes = left // 60
    offset_text = f"UTC{offset_sign}{hours:02d}:{minutes:02d}"
    is_probably_sao_paulo = offset == timedelta(hours=-3)
    return tz_name, offset_text, is_probably_sao_paulo


def check_clock_drift(server: str = "pool.ntp.org", timeout_seconds: float = 2.0) -> ClockCheck:
    if ntplib is None:
        return ClockCheck(ok=False, drift_seconds=None, message="ntplib nao instalado.")

    client = ntplib.NTPClient()
    try:
        response = client.request(server, version=3, timeout=timeout_seconds)
    except Exception as error:  # noqa: BLE001
        return ClockCheck(ok=False, drift_seconds=None, message=f"Falha ao validar relogio: {error}")

    drift = float(response.offset)
    if abs(drift) <= 1.0:
        return ClockCheck(ok=True, drift_seconds=drift, message=f"Relogio ok (desvio {drift:.3f}s).")

    return ClockCheck(
        ok=False,
        drift_seconds=drift,
        message=f"Relogio com desvio alto ({drift:.3f}s). Ajuste antes do disparo.",
    )
