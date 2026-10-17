#!/usr/bin/env python3
"""Live reset times, one line per account; uses the existing meter's quota reader."""

import argparse
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import time


def reset_time(value):
    if not value:
        return "reset unknown"
    try:
        reset = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if reset.tzinfo is None:
            return "reset unknown"
    except (TypeError, ValueError, AttributeError):
        return "reset unknown"
    minutes = max(0, int((reset - datetime.now(timezone.utc)).total_seconds()) // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    remaining = f"{days}d {hours}h" if days else f"{hours}h {minutes}m"
    return f"in {remaining} ({reset.astimezone():%a %d %b %H:%M %Z})"


def render_resets(data, error, providers):
    if error:
        return f"quota: {error}"
    rows = []
    for account in data.get("providers", []):
        if account.get("provider") not in providers:
            continue
        name = account.get("name") or account.get("provider", "?")
        windows = account.get("windows", [])
        details = []
        for window in windows:
            label = window.get("label") or window.get("id", "?")
            details.append(f"{label}: {reset_time(window.get('resetsAt'))}")
        if not details:
            state = account.get("state", {})
            details.append(f"reset unavailable ({state.get('status', 'no data')})")
        rows.append(f"{name}: " + " | ".join(details))
    return "\n".join(rows) or "quota: no matching accounts"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meter", type=Path, default=Path(__file__).with_name("meter.py"),
                        help="Quota reader module; defaults to this project's meter.py.")
    parser.add_argument("--once", action="store_true", help="Print once instead of refreshing every 60 seconds.")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("quota_reader", args.meter)
    meter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(meter)
    providers = meter.DEFAULT_PROVIDERS
    try:
        while True:
            if not args.once:
                print("\033[2J\033[HQuota reset times\n", end="", flush=True)
            # The local multi-account reader supplies its credential environment.
            env = meter.quota_env(providers) if hasattr(meter, "quota_env") else None
            data, error = meter.fetch_quota(env=env)
            print(render_resets(data, error, providers), flush=True)
            if args.once:
                return
            print(f"\nUpdated {datetime.now():%H:%M:%S} · refreshes every 60s · Ctrl+C to stop", flush=True)
            time.sleep(60)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
