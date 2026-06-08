# availability-monitor

Open-source Python framework for **poll → detect availability → notify** apps.

Extracted from [buonacaccia-monitor](https://github.com/anrighi/buonacaccia-monitor). Provides:

- CLI with `--data-dir`, `--dry-run`, `--test`
- SQLite persistence (`settings`, `executions`, `state_items` for diff alerts)
- Telegram helpers and heartbeat scheduling
- FastAPI Web UI (settings, run now, execution history)
- Docker poll loop skeleton

## Build your own monitor

1. Subclass `MonitorProvider` in `availability_monitor.protocol`.
2. Register it from a thin `monitor.py` entrypoint.
3. Optionally expose `webapp.py` via `create_app(provider)`.

```python
from availability_monitor.cli import main
from myapp.provider import PROVIDER

if __name__ == "__main__":
    raise SystemExit(main(PROVIDER))
```

## Install

```bash
pip install -e .
```

## Consumers

- **buonacaccia-monitor** — HTML scrape provider (`alert_mode="always"`)
- **book-assistant** — Walkup / Makars Mash Bar provider (`alert_mode="diff"`)

## License

MIT
