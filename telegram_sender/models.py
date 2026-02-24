from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any


TIME_FORMAT = "%H:%M:%S"


class RunStatus(str, Enum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    FLOODWAIT_EXCEEDED = "floodwait_exceeded"
    AUTH_ERROR = "auth_error"
    PERMISSION_ERROR = "permission_error"


@dataclass(slots=True)
class RunConfig:
    profile_id: str
    group_id: int
    message_text: str
    target_time_local: str
    warmup_seconds: int = 60
    retry_min_ms: int = 50
    retry_max_ms: int = 100
    max_attempt_window_sec: int = 300

    def validate(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("profile_id obrigatorio.")
        if not isinstance(self.group_id, int):
            raise ValueError("group_id deve ser inteiro.")
        text_len = len(self.message_text.strip())
        if text_len < 1 or text_len > 4096:
            raise ValueError("message_text deve ter entre 1 e 4096 caracteres.")
        try:
            datetime.strptime(self.target_time_local, TIME_FORMAT)
        except ValueError as error:
            raise ValueError("target_time_local deve estar no formato HH:MM:SS.") from error
        if self.warmup_seconds < 0:
            raise ValueError("warmup_seconds deve ser >= 0.")
        if self.retry_min_ms <= 0:
            raise ValueError("retry_min_ms deve ser > 0.")
        if self.retry_max_ms < self.retry_min_ms:
            raise ValueError("retry_max_ms deve ser >= retry_min_ms.")
        if self.max_attempt_window_sec <= 0:
            raise ValueError("max_attempt_window_sec deve ser > 0.")


@dataclass(slots=True)
class RunResult:
    status: RunStatus
    first_attempt_at: datetime | None
    success_at: datetime | None
    attempts_count: int
    details: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "first_attempt_at": self._serialize_datetime(self.first_attempt_at),
            "success_at": self._serialize_datetime(self.success_at),
            "attempts_count": self.attempts_count,
            "details": self.details,
        }

    @staticmethod
    def _serialize_datetime(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat()


@dataclass(slots=True)
class Profile:
    profile_id: str
    display_name: str
    user_id: int
    username: str | None
    phone: str | None
    last_used_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TelegramGroup:
    group_id: int
    title: str
    chat_kind: str


@dataclass(slots=True)
class AppConfig:
    api_id: int
    api_hash: str

    def validate(self) -> None:
        if self.api_id <= 0:
            raise ValueError("api_id deve ser positivo.")
        if not self.api_hash.strip():
            raise ValueError("api_hash obrigatorio.")


@dataclass(slots=True)
class ClockCheck:
    ok: bool
    drift_seconds: float | None
    message: str
