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
            parsed = _dialog_to_group(dialog)
            if parsed is not None:
                groups.append(parsed)
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


def _dialog_to_group(dialog) -> TelegramGroup | None:
    entity = getattr(dialog, "entity", None)
    if entity is None:
        return None

    is_group_dialog = bool(getattr(dialog, "is_group", False))
    is_channel_dialog = bool(getattr(dialog, "is_channel", False))
    is_mega_group = is_channel_dialog and bool(getattr(entity, "megagroup", False))
    is_broadcast_channel = is_channel_dialog and bool(getattr(entity, "broadcast", False))

    if not (is_group_dialog or is_mega_group or is_broadcast_channel):
        return None

    peer_id = int(get_peer_id(entity))
    title = getattr(dialog, "title", None) or str(peer_id)
    chat_kind = _resolve_chat_kind(is_group_dialog, is_mega_group, is_broadcast_channel)
    return TelegramGroup(group_id=peer_id, title=title, chat_kind=chat_kind)


def _resolve_chat_kind(is_group: bool, is_mega_group: bool, is_broadcast_channel: bool) -> str:
    if is_group:
        return "group"
    if is_mega_group:
        return "supergroup"
    if is_broadcast_channel:
        return "channel"
    return "unknown"
