from telethon import types
from telethon.utils import get_peer_id

from telegram_sender.telegram_auth import _dialog_to_group


class DummyDialog:
    def __init__(self, title: str, is_group: bool, is_channel: bool, entity):
        self.title = title
        self.is_group = is_group
        self.is_channel = is_channel
        self.entity = entity


def test_dialog_to_group_includes_basic_group() -> None:
    entity = types.Chat(
        id=11,
        title="Grupo Local",
        photo=types.ChatPhotoEmpty(),
        participants_count=1,
        date=None,
        version=1,
    )
    dialog = DummyDialog("Grupo Local", is_group=True, is_channel=False, entity=entity)
    result = _dialog_to_group(dialog)
    assert result is not None
    assert result.chat_kind == "group"
    assert result.group_id == get_peer_id(entity)


def test_dialog_to_group_includes_supergroup() -> None:
    entity = types.Channel(
        id=22,
        title="Supergrupo",
        photo=types.ChatPhotoEmpty(),
        date=None,
        megagroup=True,
        broadcast=False,
    )
    dialog = DummyDialog(
        "Supergrupo",
        is_group=False,
        is_channel=True,
        entity=entity,
    )
    result = _dialog_to_group(dialog)
    assert result is not None
    assert result.chat_kind == "supergroup"
    assert result.group_id == get_peer_id(entity)


def test_dialog_to_group_includes_broadcast_channel() -> None:
    entity = types.Channel(
        id=33,
        title="Canal de Ofertas",
        photo=types.ChatPhotoEmpty(),
        date=None,
        megagroup=False,
        broadcast=True,
    )
    dialog = DummyDialog(
        "Canal de Ofertas",
        is_group=False,
        is_channel=True,
        entity=entity,
    )
    result = _dialog_to_group(dialog)
    assert result is not None
    assert result.chat_kind == "channel"
    assert result.group_id == get_peer_id(entity)


def test_dialog_to_group_excludes_private_chat() -> None:
    entity = types.User(
        id=44,
        is_self=False,
        contact=False,
        mutual_contact=False,
        deleted=False,
        bot=False,
        bot_chat_history=False,
        bot_nochats=False,
        verified=False,
        restricted=False,
        min=False,
        bot_inline_geo=False,
        support=False,
        scam=False,
        apply_min_photo=False,
        fake=False,
        bot_attach_menu=False,
        premium=False,
        attach_menu_enabled=False,
        bot_can_edit=False,
        close_friend=False,
        stories_hidden=False,
        stories_unavailable=False,
        contact_require_premium=False,
        bot_business=False,
        bot_has_main_app=False,
        access_hash=1,
        first_name="Contato",
    )
    dialog = DummyDialog("Contato", is_group=False, is_channel=False, entity=entity)
    assert _dialog_to_group(dialog) is None
