from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class SessionVaultError(Exception):
    """Raised when vault cannot be decrypted or parsed."""


class SessionVault:
    """Encrypted local storage for Telegram StringSession values."""

    def __init__(self, path: Path, master_password: str):
        self._path = path
        self._master_password = master_password
        self._salt = os.urandom(16)
        self._sessions: dict[str, str] = {}
        if self._path.exists():
            self._load()

    def set_session(self, profile_id: str, session_value: str) -> None:
        self._sessions[profile_id] = session_value

    def get_session(self, profile_id: str) -> str | None:
        return self._sessions.get(profile_id)

    def remove_session(self, profile_id: str) -> None:
        self._sessions.pop(profile_id, None)

    def profile_ids(self) -> list[str]:
        return sorted(self._sessions.keys())

    def save(self) -> None:
        cipher = Fernet(self._derive_key(self._master_password, self._salt))
        payload_raw = json.dumps(self._sessions, ensure_ascii=True, sort_keys=True).encode("utf-8")
        token = cipher.encrypt(payload_raw)
        envelope = {
            "salt": base64.urlsafe_b64encode(self._salt).decode("utf-8"),
            "token": token.decode("utf-8"),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(envelope, ensure_ascii=True), encoding="utf-8")

    def _load(self) -> None:
        try:
            envelope = json.loads(self._path.read_text(encoding="utf-8"))
            salt_raw = envelope["salt"].encode("utf-8")
            token = envelope["token"].encode("utf-8")
            self._salt = base64.urlsafe_b64decode(salt_raw)
        except (KeyError, ValueError, json.JSONDecodeError) as error:
            raise SessionVaultError("Arquivo de sessao invalido.") from error

        cipher = Fernet(self._derive_key(self._master_password, self._salt))
        try:
            payload = cipher.decrypt(token)
        except InvalidToken as error:
            raise SessionVaultError("Senha mestra incorreta.") from error

        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise SessionVaultError("Conteudo de sessao corrompido.") from error

        if not isinstance(decoded, dict):
            raise SessionVaultError("Formato interno de sessao invalido.")

        cast_sessions: dict[str, str] = {}
        for key, value in decoded.items():
            if isinstance(key, str) and isinstance(value, str):
                cast_sessions[key] = value
        self._sessions = cast_sessions

    @staticmethod
    def _derive_key(master_password: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=390_000,
        )
        raw_key = kdf.derive(master_password.encode("utf-8"))
        return base64.urlsafe_b64encode(raw_key)

