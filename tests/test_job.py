import os
import tempfile
import unittest
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from availability_monitor.job import run_stored_monitor_pass
from availability_monitor.protocol import MonitorProvider, RunReport, SettingField, StorageHandle


@dataclass
class DummyConfig:
    value: str


class DummyProvider(MonitorProvider):
    name = "dummy"
    title = "Dummy Monitor"
    alert_mode = "diff"

    def default_settings(self) -> dict[str, str]:
        return {"foo": "bar"}

    def allowed_setting_keys(self) -> frozenset[str]:
        return frozenset({"foo"})

    def setting_fields(self) -> list[SettingField]:
        return [SettingField(key="foo", label="Foo")]

    def load_config(
        self,
        settings: dict[str, str],
        env: dict[str, str],
        *,
        storage: StorageHandle,
    ) -> DummyConfig:
        return DummyConfig(value=settings.get("foo", ""))

    def run_cycle(self, cfg: DummyConfig, *, storage: StorageHandle) -> RunReport:
        return RunReport(exit_code=0, summary={"foo": cfg.value})

    def build_heartbeat_message(self, report: RunReport, cfg: DummyConfig) -> str:
        return f"heartbeat {cfg.value}"

    def cli_test(self, args: Namespace) -> int:
        return 0


class JobTests(unittest.TestCase):
    def test_stored_pass_writes_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            os.environ["HEARTBEAT_INTERVAL_SECONDS"] = "0"
            result = run_stored_monitor_pass(DummyProvider(), data_dir)
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(result["summary"]["foo"], "bar")


if __name__ == "__main__":
    unittest.main()
