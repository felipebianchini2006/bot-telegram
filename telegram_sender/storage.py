from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from telegram_sender.models import AppConfig, Profile, RunConfig, RunResult


class ProfileStore:
    def __init__(self, path: Path):
        self._path = path

    def load(self) -> list[Profile]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        items = raw.get("profiles", [])
        profiles: list[Profile] = []
        for item in items:
            try:
                profiles.append(Profile(**item))
            except TypeError:
                continue
        return profiles

    def save(self, profiles: list[Profile]) -> None:
        payload = {"profiles": [profile.to_dict() for profile in profiles]}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def upsert(self, profile: Profile) -> None:
        profiles = self.load()
        updated = False
        for index, existing in enumerate(profiles):
            if existing.profile_id == profile.profile_id:
                profiles[index] = profile
                updated = True
                break
        if not updated:
            profiles.append(profile)
        self.save(profiles)

    def remove(self, profile_id: str) -> None:
        profiles = [profile for profile in self.load() if profile.profile_id != profile_id]
        self.save(profiles)


class AppConfigStore:
    def __init__(self, path: Path):
        self._path = path

    def load(self) -> AppConfig | None:
        if not self._path.exists():
            return None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            config = AppConfig(api_id=int(raw["api_id"]), api_hash=str(raw["api_hash"]))
            config.validate()
            return config
        except (ValueError, KeyError, json.JSONDecodeError):
            return None

    def save(self, config: AppConfig) -> None:
        config.validate()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(asdict(config), ensure_ascii=True, indent=2), encoding="utf-8")


class RunLogger:
    def __init__(self, path: Path):
        self._path = path

    def log_run(
        self,
        run_config: RunConfig,
        run_result: RunResult,
        group_title: str,
        profile_identity: str,
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "logged_at": datetime.now().astimezone().isoformat(),
            "profile_hash": self._hash_profile(profile_identity),
            "profile_id": run_config.profile_id,
            "group_id": run_config.group_id,
            "group_title": group_title,
            "target_time_local": run_config.target_time_local,
            "first_attempt_at": run_result.to_dict()["first_attempt_at"],
            "success_at": run_result.to_dict()["success_at"],
            "attempts_count": run_result.attempts_count,
            "status": run_result.status.value,
            "details": run_result.details,
        }
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=True) + "\n")

    @staticmethod
    def _hash_profile(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

