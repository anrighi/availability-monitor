from __future__ import annotations

from abc import ABC, abstractmethod
from argparse import Namespace
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

AlertMode = Literal["always", "diff"]


@dataclass
class RunReport:
    exit_code: int
    alerts: list[str] = field(default_factory=list)
    error: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class SettingField:
    key: str
    label: str
    field_type: Literal["text", "url", "password", "number", "textarea"] = "text"
    required: bool = False
    placeholder: str = ""
    help_text: str = ""


@dataclass
class StorageHandle:
    db_file: Path


class MonitorProvider(ABC):
    name: str = "monitor"
    title: str = "Availability Monitor"
    alert_mode: AlertMode = "diff"

    @abstractmethod
    def default_settings(self) -> dict[str, str]:
        raise NotImplementedError

    @abstractmethod
    def allowed_setting_keys(self) -> frozenset[str]:
        raise NotImplementedError

    @abstractmethod
    def setting_fields(self) -> list[SettingField]:
        raise NotImplementedError

    @abstractmethod
    def load_config(
        self,
        settings: dict[str, str],
        env: dict[str, str],
        *,
        storage: StorageHandle,
    ) -> Any:
        raise NotImplementedError

    @abstractmethod
    def run_cycle(self, cfg: Any, *, storage: StorageHandle) -> RunReport:
        raise NotImplementedError

    @abstractmethod
    def build_heartbeat_message(self, report: RunReport, cfg: Any) -> str:
        raise NotImplementedError

    def shared_setting_keys(self) -> frozenset[str]:
        return frozenset({"telegram_bot_token", "telegram_chat_id"})

    def all_setting_keys(self) -> frozenset[str]:
        return self.allowed_setting_keys() | self.shared_setting_keys()

    def env_key_for_setting(self, key: str) -> str:
        return key.upper()

    def merge_settings_with_env(
        self, settings: dict[str, str], env: dict[str, str]
    ) -> dict[str, str]:
        merged = dict(settings)
        for key in self.all_setting_keys():
            env_key = self.env_key_for_setting(key)
            env_val = (env.get(env_key) or "").strip()
            if env_val:
                merged[key] = env_val
        return merged

    def validate_settings_update(
        self,
        updates: dict[str, str],
        stored: dict[str, str],
        effective: dict[str, str],
    ) -> str | None:
        return None

    def cli_test(self, args: Namespace) -> int:
        return 1

    def telegram_test_message(self) -> str:
        return f"{self.title}: test message."

    def extra_dashboard_context(self, storage: StorageHandle) -> dict[str, Any]:
        return {}
