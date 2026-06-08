from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from availability_monitor.job import run_stored_monitor_pass
from availability_monitor.protocol import MonitorProvider, StorageHandle


def build_parser(provider: MonitorProvider) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"{provider.title} monitor")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Use SQLite settings under this directory (Docker / UI mode)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not send notifications",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--telegram-dry-run",
        action="store_true",
        help="Log Telegram payload instead of sending",
    )
    parser.add_argument(
        "--trust-proxy-env",
        action="store_true",
        help="Use HTTP_PROXY/HTTPS_PROXY from environment",
    )
    parser.add_argument(
        "--test",
        metavar="ARG",
        help="Provider-specific probe (e.g. event id or date)",
    )
    return parser


def main(provider: MonitorProvider) -> int:
    parser = build_parser(provider)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if args.test is not None:
        args.test_arg = args.test
        return int(provider.cli_test(args))

    extra_env: dict[str, str] = {}
    if args.verbose:
        extra_env["MONITOR_VERBOSE"] = "1"

    if args.data_dir is not None:
        data_dir = args.data_dir.expanduser().resolve()
        result = run_stored_monitor_pass(
            provider,
            data_dir,
            dry_run=args.dry_run,
            verbose=args.verbose,
            telegram_dry_run=args.telegram_dry_run,
            trust_proxy_env=args.trust_proxy_env,
            extra_env=extra_env,
        )
        return int(result.get("exit_code", 1))

    data_dir = Path(os.environ.get("APP_DATA_DIR", "/tmp/monitor-data")).resolve()
    result = run_stored_monitor_pass(
        provider,
        data_dir,
        dry_run=args.dry_run,
        verbose=args.verbose,
        telegram_dry_run=args.telegram_dry_run,
        trust_proxy_env=args.trust_proxy_env,
        extra_env=extra_env,
    )
    return int(result.get("exit_code", 1))
