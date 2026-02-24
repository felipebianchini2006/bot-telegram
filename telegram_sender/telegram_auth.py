from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.utils import get_peer_id

from telegram_sender.models import TelegramGroup


@dataclass(slots=True)
class LoginResult:
    profile_id: str
    display_name: str
    user_id: int
    username: str | None
    phone: str | None
    session_string: str


def build_client(session_string: str, api_id: int, api_hash: str) -> TelegramClient:
    return TelegramClient(StringSession(session_string), api_id, api_hash)


async def login_with_qr(
    api_id: int,
    api_hash: str,
    qr_callback: Callable[[str], None],
    timeout_seconds: int = 180,
) -> LoginResult:
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        qr_login = await client.qr_login()
        qr_callback(qr_login.url)
        await qr_login.wait(timeout=timeout_seconds)
        me = await client.get_me()
        if me is None:
            raise RuntimeError("Nao foi possivel obter dados da conta apos login.")
        session_string = client.session.save()
        display_name = _compose_display_name(me.first_name, me.last_name, me.id)
        return LoginResult(
            profile_id=str(me.id),
            display_name=display_name,
            user_id=me.id,
            username=getattr(me, "username", None),
            phone=getattr(me, "phone", None),
            session_string=session_string,
        )
    finally:
        await client.disconnect()


async def list_groups(session_string: str, api_id: int, api_hash: str) -> list[TelegramGroup]:
    client = build_client(session_string, api_id, api_hash)
    await client.connect()
    try:
        authorized = await client.is_user_authorized()
        if not authorized:
            raise RuntimeError("Sessao nao autorizada. Refaca o login via QR.")

        groups: list[TelegramGroup] = []
        async for dialog in client.iter_dialogs():
            is_group_dialog = dialog.is_group
            is_mega_group = dialog.is_channel and bool(getattr(dialog.entity, "megagroup", False))
            if is_group_dialog or is_mega_group:
                peer_id = int(get_peer_id(dialog.entity))
                groups.append(TelegramGroup(group_id=peer_id, title=dialog.title or str(peer_id)))
        groups.sort(key=lambda item: item.title.lower())
        return groups
    finally:
        await client.disconnect()


async def quick_connect_check(session_string: str, api_id: int, api_hash: str) -> None:
    client = build_client(session_string, api_id, api_hash)
    await client.connect()
    try:
        authorized = await client.is_user_authorized()
        if not authorized:
            raise RuntimeError("Sessao nao autorizada.")
    finally:
        await client.disconnect()


def _compose_display_name(first_name: str | None, last_name: str | None, user_id: int) -> str:
    pieces = [piece for piece in [first_name, last_name] if piece]
    if pieces:
        return f"{' '.join(pieces)} ({user_id})"
    return f"Conta {user_id}"
