import asyncio
import types as pytypes

from telethon import types
from telethon.utils import get_peer_id

import telegram_sender.telegram_auth as telegram_auth
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


def test_login_with_phone_code_success(monkeypatch) -> None:
    class DummyErrors:
        class PhoneNumberInvalidError(Exception):
            pass

        class PhoneCodeInvalidError(Exception):
            pass

        class PhoneCodeExpiredError(Exception):
            pass

        class SessionPasswordNeededError(Exception):
            pass

        class PasswordHashInvalidError(Exception):
            pass

    class FakeSession:
        @staticmethod
        def save() -> str:
            return "session-123"

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            self.session = FakeSession()
            self.disconnect_called = False

        async def connect(self) -> None:
            return

        async def disconnect(self) -> None:
            self.disconnect_called = True

        async def send_code_request(self, _phone: str):
            return pytypes.SimpleNamespace(phone_code_hash="hash-1")

        async def sign_in(self, **_kwargs) -> None:
            return

        async def get_me(self):
            return pytypes.SimpleNamespace(
                id=123,
                first_name="Maria",
                last_name="Silva",
                username="maria",
                phone="+5511999999999",
            )

    monkeypatch.setattr(telegram_auth, "telethon_errors", DummyErrors)
    monkeypatch.setattr(telegram_auth, "TelegramClient", FakeClient)

    statuses: list[str] = []
    result = asyncio.run(
        telegram_auth.login_with_phone_code(
            api_id=1,
            api_hash="hash",
            phone_number="+5511999999999",
            code_callback=lambda: "12345",
            status_callback=statuses.append,
        )
    )
    assert result.profile_id == "123"
    assert result.display_name == "Maria Silva (123)"
    assert result.username == "maria"
    assert result.phone == "+5511999999999"
    assert result.session_string == "session-123"
    assert "Codigo enviado. Informe o codigo recebido no Telegram." in statuses


def test_login_with_phone_code_requires_2fa(monkeypatch) -> None:
    class DummyErrors:
        class PhoneNumberInvalidError(Exception):
            pass

        class PhoneCodeInvalidError(Exception):
            pass

        class PhoneCodeExpiredError(Exception):
            pass

        class SessionPasswordNeededError(Exception):
            pass

        class PasswordHashInvalidError(Exception):
            pass

    class FakeSession:
        @staticmethod
        def save() -> str:
            return "session-2fa"

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            self.session = FakeSession()
            self._first_sign_in_call = True

        async def connect(self) -> None:
            return

        async def disconnect(self) -> None:
            return

        async def send_code_request(self, _phone: str):
            return pytypes.SimpleNamespace(phone_code_hash="hash-2")

        async def sign_in(self, **kwargs) -> None:
            if "password" in kwargs:
                return
            if self._first_sign_in_call:
                self._first_sign_in_call = False
                raise DummyErrors.SessionPasswordNeededError()

        async def get_me(self):
            return pytypes.SimpleNamespace(
                id=999,
                first_name="Conta",
                last_name=None,
                username=None,
                phone="+5511888888888",
            )

    monkeypatch.setattr(telegram_auth, "telethon_errors", DummyErrors)
    monkeypatch.setattr(telegram_auth, "TelegramClient", FakeClient)

    result = asyncio.run(
        telegram_auth.login_with_phone_code(
            api_id=1,
            api_hash="hash",
            phone_number="+5511888888888",
            code_callback=lambda: "67890",
            password_callback=lambda: "senha-2fa",
        )
    )
    assert result.profile_id == "999"
    assert result.display_name == "Conta (999)"
