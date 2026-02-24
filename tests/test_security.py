from pathlib import Path

import pytest

from telegram_sender.security import SessionVault, SessionVaultError


def test_session_vault_roundtrip(tmp_path: Path) -> None:
    vault_path = tmp_path / "sessions.enc"
    vault = SessionVault(vault_path, "senha-forte")
    vault.set_session("p1", "string-session")
    vault.save()

    loaded = SessionVault(vault_path, "senha-forte")
    assert loaded.get_session("p1") == "string-session"


def test_session_vault_rejects_invalid_password(tmp_path: Path) -> None:
    vault_path = tmp_path / "sessions.enc"
    vault = SessionVault(vault_path, "senha-correta")
    vault.set_session("p1", "string-session")
    vault.save()

    with pytest.raises(SessionVaultError):
        SessionVault(vault_path, "senha-errada")

