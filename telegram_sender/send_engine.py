from __future__ import annotations

import asyncio
import random
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from telethon import TelegramClient
from telethon.sessions import StringSession

from telegram_sender.models import RunConfig, RunResult, RunStatus
from telegram_sender.time_engine import compute_target_datetime, compute_warmup_datetime, format_countdown

StatusCallback = Callable[[str], None]
SleepCallable = Callable[[float], Awaitable[None]]
NowCallable = Callable[[], datetime]
UniformCallable = Callable[[int, int], float]


@dataclass(slots=True)
class SendEngine:
    client_factory: Callable[[str, int, str], Any] | None = None
    now_provider: NowCallable | None = None
    sleep_callable: SleepCallable = asyncio.sleep
    uniform_callable: UniformCallable = random.uniform

    async def run(
        self,
        run_config: RunConfig,
        session_string: str,
        api_id: int,
        api_hash: str,
        stop_event: threading.Event | None = None,
        status_callback: StatusCallback | None = None,
    ) -> RunResult:
        run_config.validate()
        now = self._now
        emit = status_callback or (lambda message: None)
        stop = stop_event or threading.Event()
        first_attempt_at: datetime | None = None
        last_permission_error: Exception | None = None
        last_status_emit_at: datetime | None = None
        attempts_count = 0

        target_at = compute_target_datetime(
            run_config.target_time_local,
            now(),
            rollover_grace_seconds=run_config.max_attempt_window_sec,
        )
        warmup_at = compute_warmup_datetime(target_at, run_config.warmup_seconds)
        deadline = target_at + timedelta(seconds=run_config.max_attempt_window_sec)
        emit(
            "Execucao agendada para "
            f"{target_at.strftime('%Y-%m-%d %H:%M:%S')} "
            f"(warmup em {warmup_at.strftime('%H:%M:%S')})."
        )

        client = self._create_client(session_string, api_id, api_hash)

        try:
            connected = await self._ensure_connected(client, emit)
            if not connected:
                return self._result(
                    RunStatus.NETWORK_ERROR,
                    first_attempt_at,
                    None,
                    attempts_count,
                    "Nao foi possivel conectar ao Telegram.",
                )
            authorized = await client.is_user_authorized()
            if not authorized:
                return self._result(
                    RunStatus.AUTH_ERROR,
                    first_attempt_at,
                    None,
                    attempts_count,
                    "Sessao nao autorizada. Refaca o login.",
                )

            group_entity = await client.get_entity(run_config.group_id)

            warmup_ready = await self._wait_until(
                warmup_at,
                stop,
                emit,
                "Aguardando warmup",
            )
            if not warmup_ready:
                return self._result(
                    RunStatus.TIMEOUT,
                    first_attempt_at,
                    None,
                    attempts_count,
                    "Execucao interrompida antes do warmup.",
                )
            emit("Warmup iniciado. Conexao estabilizada.")

            if run_config.race_mode and run_config.pre_fire_seconds > 0:
                fire_at = target_at - timedelta(seconds=run_config.pre_fire_seconds)
                emit(f"Modo corrida: pre-fire {run_config.pre_fire_seconds}s antes do alvo.")
            else:
                fire_at = target_at

            if run_config.race_mode and run_config.keepalive_interval_sec > 0:
                target_ready = await self._wait_with_keepalive(
                    fire_at, stop, emit, client, run_config.keepalive_interval_sec,
                )
            else:
                target_ready = await self._wait_until(
                    fire_at, stop, emit, "Aguardando horario alvo",
                )
            if not target_ready:
                return self._result(
                    RunStatus.TIMEOUT,
                    first_attempt_at,
                    None,
                    attempts_count,
                    "Execucao interrompida antes do horario alvo.",
                )
            emit("Janela de envio iniciada.")

            while now() <= deadline:
                if stop.is_set():
                    return self._result(
                        RunStatus.TIMEOUT,
                        first_attempt_at,
                        None,
                        attempts_count,
                        "Execucao interrompida manualmente.",
                    )

                attempts_count += 1
                if first_attempt_at is None:
                    first_attempt_at = now()

                try:
                    await client.send_message(group_entity, run_config.message_text)
                    success_at = now()
                    emit(f"Mensagem enviada com sucesso na tentativa {attempts_count}.")
                    if run_config.race_mode and first_attempt_at is not None:
                        elapsed = (success_at - first_attempt_at).total_seconds()
                        emit(f"Corrida finalizada: {attempts_count} tentativas em {elapsed:.3f}s.")
                    return self._result(
                        RunStatus.SUCCESS,
                        first_attempt_at,
                        success_at,
                        attempts_count,
                        None,
                    )
                except Exception as error:  # noqa: BLE001
                    flood_seconds = self._extract_flood_wait_seconds(error)
                    if flood_seconds is not None:
                        projected = now() + timedelta(seconds=flood_seconds)
                        if projected > deadline:
                            emit(f"FloodWait de {flood_seconds}s excede a janela restante.")
                            return self._result(
                                RunStatus.FLOODWAIT_EXCEEDED,
                                first_attempt_at,
                                None,
                                attempts_count,
                                f"FloodWait de {flood_seconds}s.",
                            )
                        emit(f"FloodWait detectado: aguardando {flood_seconds}s.")
                        await self.sleep_callable(float(flood_seconds))
                        continue

                    if self._is_permission_error(error):
                        if self._is_retryable_permission_error(error):
                            last_permission_error = error
                            remaining_seconds = max((deadline - now()).total_seconds(), 0.0)
                            if remaining_seconds <= 0:
                                return self._result(
                                    RunStatus.PERMISSION_ERROR,
                                    first_attempt_at,
                                    None,
                                    attempts_count,
                                    str(error),
                                )

                            if run_config.race_mode:
                                wait_seconds = min(
                                    run_config.race_retry_ms / 1000.0,
                                    remaining_seconds,
                                )
                                now_ts = now()
                                if last_status_emit_at is None or (now_ts - last_status_emit_at).total_seconds() >= run_config.status_throttle_ms / 1000.0:
                                    emit(
                                        f"Corrida: tentativa {attempts_count}, "
                                        f"restam {remaining_seconds:.1f}s."
                                    )
                                    last_status_emit_at = now_ts
                            else:
                                wait_seconds = min(
                                    self.uniform_callable(run_config.retry_min_ms, run_config.retry_max_ms) / 1000.0,
                                    remaining_seconds,
                                )
                                emit(
                                    "Permissao temporariamente negada; "
                                    f"nova tentativa em {wait_seconds * 1000:.0f}ms."
                                )

                            await self.sleep_callable(wait_seconds)
                            continue
                        return self._result(
                            RunStatus.PERMISSION_ERROR,
                            first_attempt_at,
                            None,
                            attempts_count,
                            str(error),
                        )

                    if self._is_auth_error(error):
                        return self._result(
                            RunStatus.AUTH_ERROR,
                            first_attempt_at,
                            None,
                            attempts_count,
                            str(error),
                        )

                    emit(f"Falha de rede na tentativa {attempts_count}: {error}. Reconectando...")
                    reconnected = await self._reconnect(client, emit)
                    if not reconnected:
                        return self._result(
                            RunStatus.NETWORK_ERROR,
                            first_attempt_at,
                            None,
                            attempts_count,
                            f"Falha ao reconectar: {error}",
                        )
                    wait_seconds = self.uniform_callable(run_config.retry_min_ms, run_config.retry_max_ms) / 1000.0
                    await self.sleep_callable(wait_seconds)
                    continue

            if last_permission_error is not None:
                return self._result(
                    RunStatus.PERMISSION_ERROR,
                    first_attempt_at,
                    None,
                    attempts_count,
                    str(last_permission_error),
                )
            return self._result(
                RunStatus.TIMEOUT,
                first_attempt_at,
                None,
                attempts_count,
                "Janela de tentativa encerrada sem envio confirmado.",
            )
        finally:
            await self._safe_disconnect(client)

    @property
    def _now(self) -> NowCallable:
        if self.now_provider is not None:
            return self.now_provider
        return lambda: datetime.now().astimezone()

    def _create_client(self, session_string: str, api_id: int, api_hash: str) -> Any:
        if self.client_factory is not None:
            return self.client_factory(session_string, api_id, api_hash)
        return TelegramClient(StringSession(session_string), api_id, api_hash)

    async def _ensure_connected(self, client: Any, emit: StatusCallback) -> bool:
        try:
            await client.connect()
            return True
        except Exception as error:  # noqa: BLE001
            emit(f"Falha inicial de conexao: {error}")
            return False

    async def _reconnect(self, client: Any, emit: StatusCallback) -> bool:
        await self._safe_disconnect(client)
        try:
            await client.connect()
            emit("Reconectado ao Telegram.")
            return True
        except Exception as error:  # noqa: BLE001
            emit(f"Reconexao falhou: {error}")
            return False

    async def _safe_disconnect(self, client: Any) -> None:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            return

    async def _wait_with_keepalive(
        self,
        target_at: datetime,
        stop_event: threading.Event,
        emit: StatusCallback,
        client: Any,
        keepalive_interval_sec: int,
    ) -> bool:
        while True:
            now_value = self._now()
            if now_value >= target_at:
                return True
            remaining = (target_at - now_value).total_seconds()
            wait_chunk = min(remaining, float(keepalive_interval_sec))
            chunk_target = now_value + timedelta(seconds=wait_chunk)
            ready = await self._wait_until(chunk_target, stop_event, emit, "Aguardando horario alvo")
            if not ready:
                return False
            if self._now() < target_at:
                try:
                    await client.get_me()
                except Exception:  # noqa: BLE001
                    emit("Keep-alive falhou, tentando reconectar...")
                    reconnected = await self._reconnect(client, emit)
                    if not reconnected:
                        emit("Reconexao apos keep-alive falhou.")

    async def _wait_until(
        self,
        target_at: datetime,
        stop_event: threading.Event,
        emit: StatusCallback,
        label: str,
    ) -> bool:
        last_second: int | None = None
        busy_wait_window_seconds = 0.010

        while True:
            if stop_event.is_set():
                return False
            now_value = self._now()
            if now_value >= target_at:
                return True

            remaining = target_at - now_value
            now_second = int(remaining.total_seconds())
            if now_second != last_second:
                emit(f"{label}: {format_countdown(remaining)}")
                last_second = now_second

            remaining_seconds = remaining.total_seconds()
            if remaining_seconds <= busy_wait_window_seconds:
                # Espera ativa apenas nos milissegundos finais para minimizar atraso de disparo.
                current = now_value
                while current < target_at:
                    if stop_event.is_set():
                        return False
                    candidate = self._now()
                    if candidate <= current:
                        # Fallback para relogios simulados que nao avancam sem sleep explicito.
                        await self.sleep_callable(0.0005)
                        candidate = self._now()
                    current = candidate
                return True

            await self.sleep_callable(min(0.25, max(0.001, remaining_seconds - busy_wait_window_seconds)))

    @staticmethod
    def _extract_flood_wait_seconds(error: Exception) -> int | None:
        name = error.__class__.__name__
        if "FloodWait" not in name:
            return None
        seconds_value = getattr(error, "seconds", None)
        if isinstance(seconds_value, int):
            return max(seconds_value, 0)
        return None

    @staticmethod
    def _is_permission_error(error: Exception) -> bool:
        return error.__class__.__name__ in {
            "ChatWriteForbiddenError",
            "UserBannedInChannelError",
            "ChatAdminRequiredError",
            "ChannelPrivateError",
        }

    @staticmethod
    def _is_retryable_permission_error(error: Exception) -> bool:
        return error.__class__.__name__ in {
            "ChatWriteForbiddenError",
        }

    @staticmethod
    def _is_auth_error(error: Exception) -> bool:
        return error.__class__.__name__ in {
            "AuthKeyUnregisteredError",
            "UnauthorizedError",
            "SessionPasswordNeededError",
            "PhoneCodeInvalidError",
            "PhoneNumberUnoccupiedError",
            "UserDeactivatedError",
        }

    @staticmethod
    def _result(
        status: RunStatus,
        first_attempt_at: datetime | None,
        success_at: datetime | None,
        attempts_count: int,
        details: str | None,
    ) -> RunResult:
        return RunResult(
            status=status,
            first_attempt_at=first_attempt_at,
            success_at=success_at,
            attempts_count=attempts_count,
            details=details,
        )
