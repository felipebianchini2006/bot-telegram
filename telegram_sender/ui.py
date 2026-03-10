from __future__ import annotations

import asyncio
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

import qrcode
from PIL import ImageTk

from telegram_sender.models import AppConfig, Profile, RunConfig, RunResult, TelegramGroup
from telegram_sender.paths import APP_CONFIG_PATH, PROFILES_PATH, RUNS_LOG_PATH, SESSIONS_PATH, ensure_data_dir
from telegram_sender.security import SessionVault, SessionVaultError
from telegram_sender.send_engine import SendEngine
from telegram_sender.storage import AppConfigStore, ProfileStore, RunLogger
from telegram_sender.telegram_auth import LoginResult, list_groups, login_with_phone_code, login_with_qr
from telegram_sender.time_engine import check_clock_drift, timezone_summary


class TelegramSenderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Telegram Sender MVP")
        self.root.geometry("920x760")

        ensure_data_dir()
        self.profile_store = ProfileStore(PROFILES_PATH)
        self.config_store = AppConfigStore(APP_CONFIG_PATH)
        self.run_logger = RunLogger(RUNS_LOG_PATH)
        self.vault = self._open_or_create_vault()
        if self.vault is None:
            raise RuntimeError("Aplicacao encerrada sem senha mestra.")

        self.profile_items: dict[str, Profile] = {}
        self.group_items: dict[str, TelegramGroup] = {}
        self.run_thread: threading.Thread | None = None
        self.run_stop_event = threading.Event()
        self.qr_window: tk.Toplevel | None = None
        self.qr_image_label: ttk.Label | None = None
        self.qr_photo_image = None

        self.api_id_var = tk.StringVar()
        self.api_hash_var = tk.StringVar()
        self.profile_var = tk.StringVar()
        self.group_var = tk.StringVar()
        self.target_time_var = tk.StringVar(value="19:00:00")
        self.timezone_var = tk.StringVar(value="")
        self.race_mode_var = tk.BooleanVar(value=False)
        self.pre_fire_var = tk.StringVar(value="5")
        self.race_retry_var = tk.StringVar(value="5")

        self._build_layout()
        self._load_initial_data()
        self._refresh_timezone_banner()

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        container = ttk.Frame(self.root, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(7, weight=1)

        credentials = ttk.LabelFrame(container, text="Credenciais Telegram API", padding=10)
        credentials.grid(row=0, column=0, sticky="ew")
        credentials.columnconfigure(1, weight=1)
        credentials.columnconfigure(3, weight=1)

        ttk.Label(credentials, text="API ID").grid(row=0, column=0, sticky="w")
        ttk.Entry(credentials, textvariable=self.api_id_var, width=18).grid(row=0, column=1, sticky="w", padx=(8, 16))
        ttk.Label(credentials, text="API Hash").grid(row=0, column=2, sticky="w")
        ttk.Entry(credentials, textvariable=self.api_hash_var, width=45).grid(row=0, column=3, sticky="ew", padx=(8, 0))
        ttk.Button(credentials, text="Salvar credenciais", command=self._save_credentials).grid(
            row=0,
            column=4,
            padx=(10, 0),
        )

        profile_frame = ttk.LabelFrame(container, text="Perfil e Login", padding=10)
        profile_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        profile_frame.columnconfigure(0, weight=1)

        self.profile_combo = ttk.Combobox(profile_frame, textvariable=self.profile_var, state="readonly")
        self.profile_combo.grid(row=0, column=0, sticky="ew")
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _: self._on_profile_selected())

        self.login_button = ttk.Button(profile_frame, text="Novo login via QR", command=self._start_qr_login)
        self.login_button.grid(row=0, column=1, padx=(8, 0))
        self.login_phone_button = ttk.Button(
            profile_frame,
            text="Novo login por celular",
            command=self._start_phone_login,
        )
        self.login_phone_button.grid(row=0, column=2, padx=(8, 0))
        self.load_groups_button = ttk.Button(profile_frame, text="Carregar grupos", command=self._load_groups_for_profile)
        self.load_groups_button.grid(row=0, column=3, padx=(8, 0))

        group_frame = ttk.LabelFrame(container, text="Grupo alvo", padding=10)
        group_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        group_frame.columnconfigure(0, weight=1)
        self.group_combo = ttk.Combobox(group_frame, textvariable=self.group_var, state="readonly")
        self.group_combo.grid(row=0, column=0, sticky="ew")

        schedule_frame = ttk.LabelFrame(container, text="Horario e validacoes", padding=10)
        schedule_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        schedule_frame.columnconfigure(3, weight=1)

        ttk.Label(schedule_frame, text="Horario alvo (HH:MM:SS)").grid(row=0, column=0, sticky="w")
        ttk.Entry(schedule_frame, textvariable=self.target_time_var, width=12).grid(row=0, column=1, sticky="w", padx=(8, 12))
        ttk.Button(schedule_frame, text="Validar relogio", command=self._validate_clock).grid(row=0, column=2, sticky="w")
        ttk.Label(schedule_frame, textvariable=self.timezone_var).grid(row=0, column=3, sticky="e")

        race_frame = ttk.LabelFrame(container, text="Modo corrida (race mode)", padding=10)
        race_frame.grid(row=4, column=0, sticky="ew", pady=(10, 0))

        race_check = ttk.Checkbutton(
            race_frame, text="Ativar modo corrida",
            variable=self.race_mode_var,
            command=self._toggle_race_fields,
        )
        race_check.grid(row=0, column=0, sticky="w", padx=(0, 12))

        ttk.Label(race_frame, text="Pre-fire (s)").grid(row=0, column=1, sticky="w")
        self.pre_fire_entry = ttk.Entry(race_frame, textvariable=self.pre_fire_var, width=6, state="disabled")
        self.pre_fire_entry.grid(row=0, column=2, sticky="w", padx=(4, 12))

        ttk.Label(race_frame, text="Retry (ms)").grid(row=0, column=3, sticky="w")
        self.race_retry_entry = ttk.Entry(race_frame, textvariable=self.race_retry_var, width=6, state="disabled")
        self.race_retry_entry.grid(row=0, column=4, sticky="w", padx=(4, 0))

        message_frame = ttk.LabelFrame(container, text="Mensagem", padding=10)
        message_frame.grid(row=5, column=0, sticky="nsew", pady=(10, 0))
        message_frame.columnconfigure(0, weight=1)
        message_frame.rowconfigure(0, weight=1)
        self.message_text = ScrolledText(message_frame, height=6, wrap="word")
        self.message_text.grid(row=0, column=0, sticky="nsew")

        actions = ttk.Frame(container)
        actions.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        self.start_button = ttk.Button(actions, text="Iniciar rodada", command=self._start_run)
        self.start_button.grid(row=0, column=0, sticky="w")
        self.stop_button = ttk.Button(actions, text="Parar", command=self._stop_run, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="w", padx=(8, 0))

        status_frame = ttk.LabelFrame(container, text="Status da execucao", padding=10)
        status_frame.grid(row=7, column=0, sticky="nsew", pady=(10, 0))
        status_frame.columnconfigure(0, weight=1)
        status_frame.rowconfigure(0, weight=1)
        self.status_text = ScrolledText(status_frame, height=14, wrap="word", state="disabled")
        self.status_text.grid(row=0, column=0, sticky="nsew")

    def _load_initial_data(self) -> None:
        config = self.config_store.load()
        if config is not None:
            self.api_id_var.set(str(config.api_id))
            self.api_hash_var.set(config.api_hash)

        self._reload_profiles()
        if self.profile_combo["values"]:
            first_value = self.profile_combo["values"][0]
            self.profile_var.set(first_value)
            self._on_profile_selected()

    def _open_or_create_vault(self) -> SessionVault | None:
        if SESSIONS_PATH.exists():
            while True:
                password = simpledialog.askstring(
                    "Senha mestra",
                    "Digite a senha mestra para abrir as sessoes:",
                    show="*",
                    parent=self.root,
                )
                if password is None:
                    return None
                try:
                    return SessionVault(SESSIONS_PATH, password)
                except SessionVaultError as error:
                    messagebox.showerror("Erro", str(error), parent=self.root)

        while True:
            password = simpledialog.askstring(
                "Criar senha mestra",
                "Defina a senha mestra (minimo 6 caracteres):",
                show="*",
                parent=self.root,
            )
            if password is None:
                return None
            if len(password) < 6:
                messagebox.showerror("Erro", "Senha mestra precisa ter ao menos 6 caracteres.", parent=self.root)
                continue
            confirmation = simpledialog.askstring(
                "Confirmar senha",
                "Repita a senha mestra:",
                show="*",
                parent=self.root,
            )
            if confirmation is None:
                return None
            if confirmation != password:
                messagebox.showerror("Erro", "As senhas nao conferem.", parent=self.root)
                continue
            vault = SessionVault(SESSIONS_PATH, password)
            vault.save()
            return vault

    def _save_credentials(self) -> None:
        config = self._read_config_from_form(show_errors=True)
        if config is None:
            return
        self.config_store.save(config)
        self._append_status("Credenciais API salvas.")

    def _reload_profiles(self) -> None:
        self.profile_items.clear()
        labels = []
        for profile in self.profile_store.load():
            label = f"{profile.display_name} | perfil={profile.profile_id}"
            labels.append(label)
            self.profile_items[label] = profile
        self.profile_combo["values"] = labels

    def _on_profile_selected(self) -> None:
        selected = self.profile_var.get()
        profile = self.profile_items.get(selected)
        if profile is None:
            return
        profile.last_used_at = datetime.now().astimezone().isoformat()
        self.profile_store.upsert(profile)
        self._append_status(f"Perfil selecionado: {profile.display_name}.")

    def _start_qr_login(self) -> None:
        config = self._read_config_from_form(show_errors=True)
        if config is None:
            return
        self._set_ui_busy(True, "Aguardando escaneamento do QR Code...")
        self._open_qr_window()

        def on_qr_url(url: str) -> None:
            self.root.after(0, lambda: self._update_qr_image(url))

        def on_success(result: LoginResult) -> None:
            self._close_qr_window()
            profile = self._persist_login_result(result)
            self._set_ui_busy(False)
            self._append_status(f"Login concluido para {profile.display_name}.")

        def on_error(error: Exception) -> None:
            self._close_qr_window()
            self._set_ui_busy(False)
            messagebox.showerror("Erro de login", str(error), parent=self.root)
            self._append_status(f"Falha no login QR: {error}")

        self._run_coroutine(
            login_with_qr(config.api_id, config.api_hash, qr_callback=on_qr_url),
            on_success,
            on_error,
        )

    def _start_phone_login(self) -> None:
        config = self._read_config_from_form(show_errors=True)
        if config is None:
            return

        phone_input = self._ask_string(
            title="Login Telegram por celular",
            prompt="Digite o numero no formato internacional (ex: +5511999999999):",
        )
        if phone_input is None:
            return
        phone = phone_input.strip()
        if not phone:
            messagebox.showerror("Erro", "Numero de celular obrigatorio.", parent=self.root)
            return

        self._set_ui_busy(True, f"Solicitando codigo para {phone}...")

        def code_callback() -> str | None:
            return self._ask_string(
                title="Codigo do Telegram",
                prompt="Digite o codigo recebido no Telegram:",
            )

        def password_callback() -> str | None:
            return self._ask_string(
                title="Senha 2FA",
                prompt="Digite a senha de duas etapas:",
                show="*",
            )

        def status_callback(message: str) -> None:
            self.root.after(0, lambda text=message: self._append_status(text))

        def on_success(result: LoginResult) -> None:
            profile = self._persist_login_result(result)
            self._set_ui_busy(False)
            self._append_status(f"Login por celular concluido para {profile.display_name}.")

        def on_error(error: Exception) -> None:
            self._set_ui_busy(False)
            messagebox.showerror("Erro de login", str(error), parent=self.root)
            self._append_status(f"Falha no login por celular: {error}")

        self._run_coroutine(
            login_with_phone_code(
                api_id=config.api_id,
                api_hash=config.api_hash,
                phone_number=phone,
                code_callback=code_callback,
                password_callback=password_callback,
                status_callback=status_callback,
            ),
            on_success,
            on_error,
        )

    def _load_groups_for_profile(self) -> None:
        config = self._read_config_from_form(show_errors=True)
        if config is None:
            return

        profile = self._selected_profile()
        if profile is None:
            messagebox.showerror("Erro", "Selecione um perfil primeiro.", parent=self.root)
            return

        session_string = self.vault.get_session(profile.profile_id)
        if session_string is None:
            messagebox.showerror("Erro", "Sessao nao encontrada. Refaca o login.", parent=self.root)
            return

        self._set_ui_busy(True, "Carregando grupos da conta...")

        def on_success(groups) -> None:
            self.group_items.clear()
            labels = []
            for group in groups:
                kind_label = self._map_kind_label(group.chat_kind)
                label = f"{group.title} ({group.group_id}) - {kind_label}"
                self.group_items[label] = group
                labels.append(label)
            self.group_combo["values"] = labels
            if labels:
                self.group_var.set(labels[0])
            self._set_ui_busy(False)
            self._append_status(f"{len(labels)} grupo(s) carregado(s).")

        def on_error(error: Exception) -> None:
            self._set_ui_busy(False)
            messagebox.showerror("Erro", str(error), parent=self.root)
            self._append_status(f"Falha ao carregar grupos: {error}")

        self._run_coroutine(
            list_groups(session_string=session_string, api_id=config.api_id, api_hash=config.api_hash),
            on_success,
            on_error,
        )

    def _validate_clock(self) -> None:
        self._refresh_timezone_banner()

        def worker() -> None:
            result = check_clock_drift()
            self.root.after(0, lambda: self._apply_clock_check(result.ok, result.message))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_clock_check(self, ok: bool, message: str) -> None:
        if ok:
            self._append_status(message)
        else:
            self._append_status(f"ALERTA: {message}")
            messagebox.showwarning("Validacao de relogio", message, parent=self.root)

    def _refresh_timezone_banner(self) -> None:
        tz_name, utc_offset, is_probably_sp = timezone_summary()
        warning = "" if is_probably_sp else " | alerta: fuso diferente de SP"
        self.timezone_var.set(f"Fuso local: {tz_name} ({utc_offset}){warning}")
        if not is_probably_sp:
            self._append_status("Aviso: fuso local nao parece Sao Paulo. Verifique antes de disparar.")

    def _toggle_race_fields(self) -> None:
        state = "normal" if self.race_mode_var.get() else "disabled"
        self.pre_fire_entry.config(state=state)
        self.race_retry_entry.config(state=state)

    def _start_run(self) -> None:
        if self.run_thread is not None and self.run_thread.is_alive():
            messagebox.showwarning("Execucao em andamento", "Ja existe uma rodada ativa.", parent=self.root)
            return

        config = self._read_config_from_form(show_errors=True)
        if config is None:
            return

        profile = self._selected_profile()
        if profile is None:
            messagebox.showerror("Erro", "Selecione um perfil.", parent=self.root)
            return

        group_label = self.group_var.get().strip()
        selected_group = self.group_items.get(group_label)
        if selected_group is None:
            messagebox.showerror("Erro", "Selecione um grupo valido.", parent=self.root)
            return
        if selected_group.chat_kind == "channel":
            self._append_status(
                "Aviso: este destino e um canal. Geralmente canais sao somente leitura para membros."
            )

        message_text = self.message_text.get("1.0", "end").strip()
        race_mode = self.race_mode_var.get()
        try:
            run_config = RunConfig(
                profile_id=profile.profile_id,
                group_id=selected_group.group_id,
                message_text=message_text,
                target_time_local=self.target_time_var.get().strip(),
                race_mode=race_mode,
                pre_fire_seconds=int(self.pre_fire_var.get()) if race_mode else 0,
                race_retry_ms=int(self.race_retry_var.get()) if race_mode else 5,
            )
            run_config.validate()
        except (TypeError, ValueError) as error:
            messagebox.showerror("Erro de validacao", str(error), parent=self.root)
            return

        session_string = self.vault.get_session(profile.profile_id)
        if session_string is None:
            messagebox.showerror("Erro", "Sessao nao encontrada para este perfil.", parent=self.root)
            return

        self.run_stop_event = threading.Event()
        self._set_running_state(True)
        self._append_status("Rodada iniciada.")

        def status_callback(message: str) -> None:
            self.root.after(0, lambda: self._append_status(message))

        def worker() -> None:
            engine = SendEngine()
            try:
                run_result = asyncio.run(
                    engine.run(
                        run_config=run_config,
                        session_string=session_string,
                        api_id=config.api_id,
                        api_hash=config.api_hash,
                        stop_event=self.run_stop_event,
                        status_callback=status_callback,
                    )
                )
                self.root.after(0, lambda: self._finish_run(run_config, run_result, group_label, profile))
            except Exception as error:  # noqa: BLE001
                self.root.after(0, lambda captured=error: self._fail_run(captured))

        self.run_thread = threading.Thread(target=worker, daemon=True)
        self.run_thread.start()

    def _stop_run(self) -> None:
        if self.run_thread is None or not self.run_thread.is_alive():
            return
        self.run_stop_event.set()
        self._append_status("Solicitado encerramento da rodada atual.")

    def _finish_run(self, run_config: RunConfig, run_result: RunResult, group_label: str, profile: Profile) -> None:
        identity = f"{profile.user_id}:{profile.profile_id}"
        self.run_logger.log_run(
            run_config=run_config,
            run_result=run_result,
            group_title=group_label,
            profile_identity=identity,
        )
        self._append_status(f"Resultado final: {run_result.status.value}. Tentativas: {run_result.attempts_count}.")
        if run_result.details:
            self._append_status(f"Detalhes: {run_result.details}")
        self._set_running_state(False)

    def _fail_run(self, error: Exception) -> None:
        self._append_status(f"Falha inesperada durante execucao: {error}")
        messagebox.showerror("Erro", str(error), parent=self.root)
        self._set_running_state(False)

    def _set_running_state(self, running: bool) -> None:
        self.start_button.config(state="disabled" if running else "normal")
        self.stop_button.config(state="normal" if running else "disabled")
        self.login_button.config(state="disabled" if running else "normal")
        self.login_phone_button.config(state="disabled" if running else "normal")
        self.load_groups_button.config(state="disabled" if running else "normal")

    def _set_ui_busy(self, busy: bool, status_message: str | None = None) -> None:
        self.login_button.config(state="disabled" if busy else "normal")
        self.login_phone_button.config(state="disabled" if busy else "normal")
        self.load_groups_button.config(state="disabled" if busy else "normal")
        self.start_button.config(state="disabled" if busy else "normal")
        if status_message:
            self._append_status(status_message)

    def _read_config_from_form(self, show_errors: bool) -> AppConfig | None:
        try:
            api_id = int(self.api_id_var.get().strip())
            api_hash = self.api_hash_var.get().strip()
            config = AppConfig(api_id=api_id, api_hash=api_hash)
            config.validate()
            return config
        except (TypeError, ValueError) as error:
            if show_errors:
                messagebox.showerror(
                    "Credenciais invalidas",
                    "Informe API ID e API Hash validos.\n"
                    "Crie em https://my.telegram.org/apps",
                    parent=self.root,
                )
            self._append_status(f"Erro de credenciais: {error}")
            return None

    def _selected_profile(self) -> Profile | None:
        selected = self.profile_var.get().strip()
        return self.profile_items.get(selected)

    def _persist_login_result(self, result: LoginResult) -> Profile:
        profile = Profile(
            profile_id=result.profile_id,
            display_name=result.display_name,
            user_id=result.user_id,
            username=result.username,
            phone=result.phone,
            last_used_at=datetime.now().astimezone().isoformat(),
        )
        self.profile_store.upsert(profile)
        self.vault.set_session(profile.profile_id, result.session_string)
        self.vault.save()
        self._reload_profiles()

        for label, item in self.profile_items.items():
            if item.profile_id == profile.profile_id:
                self.profile_var.set(label)
                break
        return profile

    def _ask_string(self, title: str, prompt: str, show: str | None = None) -> str | None:
        if threading.current_thread() is threading.main_thread():
            return simpledialog.askstring(title, prompt, show=show, parent=self.root)

        response_holder: dict[str, str | None] = {"value": None}
        response_ready = threading.Event()

        def ask_on_ui() -> None:
            response_holder["value"] = simpledialog.askstring(title, prompt, show=show, parent=self.root)
            response_ready.set()

        self.root.after(0, ask_on_ui)
        response_ready.wait()
        return response_holder["value"]

    def _run_coroutine(
        self,
        coroutine,
        on_success: Callable[[object], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        def worker() -> None:
            try:
                result = asyncio.run(coroutine)
            except Exception as error:  # noqa: BLE001
                self.root.after(0, lambda captured=error: on_error(captured))
                return
            self.root.after(0, lambda payload=result: on_success(payload))

        threading.Thread(target=worker, daemon=True).start()

    def _open_qr_window(self) -> None:
        if self.qr_window is not None and self.qr_window.winfo_exists():
            self.qr_window.destroy()
        self.qr_window = tk.Toplevel(self.root)
        self.qr_window.title("Login Telegram por QR")
        self.qr_window.geometry("340x420")
        self.qr_window.resizable(False, False)
        ttk.Label(
            self.qr_window,
            text="Abra Telegram > Configuracoes > Dispositivos >\nConectar dispositivo e escaneie o QR.",
            justify="center",
        ).pack(pady=(12, 8))
        self.qr_image_label = ttk.Label(self.qr_window)
        self.qr_image_label.pack(pady=8)
        ttk.Label(self.qr_window, text="Aguardando QR...").pack()

    def _update_qr_image(self, qr_url: str) -> None:
        if self.qr_window is None or not self.qr_window.winfo_exists():
            return
        qr_image = qrcode.make(qr_url).resize((280, 280))
        self.qr_photo_image = ImageTk.PhotoImage(qr_image)
        if self.qr_image_label is not None:
            self.qr_image_label.configure(image=self.qr_photo_image)

    def _close_qr_window(self) -> None:
        if self.qr_window is not None and self.qr_window.winfo_exists():
            self.qr_window.destroy()
        self.qr_window = None
        self.qr_image_label = None
        self.qr_photo_image = None

    def _append_status(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.status_text.configure(state="normal")
        self.status_text.insert("end", f"[{stamp}] {message}\n")
        self.status_text.see("end")
        self.status_text.configure(state="disabled")

    @staticmethod
    def _map_kind_label(kind: str) -> str:
        if kind == "group":
            return "Grupo"
        if kind == "supergroup":
            return "Supergrupo"
        if kind == "channel":
            return "Canal"
        return "Desconhecido"


def run_app() -> None:
    root = tk.Tk()
    try:
        TelegramSenderApp(root)
    except RuntimeError:
        root.destroy()
        return
    root.mainloop()
