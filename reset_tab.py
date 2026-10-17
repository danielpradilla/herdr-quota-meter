#!/usr/bin/env python3
"""Remaining quota bars and live reset countdowns, using the existing quota reader."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import curses
from datetime import datetime, timezone
import importlib.util
import math
from pathlib import Path
import shutil
import time


def reset_time(value, now):
    if not isinstance(value, str):
        return "reset unknown"
    try:
        reset = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if reset.tzinfo is None:
            return "reset unknown"
    except ValueError:
        return "reset unknown"
    seconds = max(0, math.ceil((reset - now).total_seconds()))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    clock = f"{hours:02}:{minutes:02}:{seconds:02}"
    if days:
        clock = f"{days}d {clock}"
    return f"{clock} · {reset.astimezone():%d %b %H:%M %Z}"


def quota_bar(value, width):
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return "[" + "?" * width + "]   ?%", 0
    value = min(100, max(0, value))
    filled = math.floor(value * width / 100)
    state = 3 if value <= 15 else 2 if value <= 30 else 1
    return "[" + "█" * filled + "░" * (width - filled) + f"] {value:3.0f}%", state


def dashboard_rows(data, error, providers, width, now):
    rows = []
    if error:
        rows.append((f"FETCH ERROR · {error}", 3))
        if data:
            rows.append(("Last successful reading below; quotas may be stale.", 2))
    for account in (data or {}).get("providers", []):
        if account.get("provider") not in providers:
            continue
        name = account.get("name") or account.get("provider", "?")
        windows = sorted(account.get("windows", []),
                         key=lambda w: {"session": 0, "weekly": 1, "monthly": 2}.get(w.get("kind"), 3))
        if not windows:
            state = account.get("state", {}).get("status", "no data")
            rows.extend([(f"{name} · {state}", 0), ("", 0)])
            continue
        cells = []
        for window in windows:
            label = {"session": "5h", "weekly": "7d", "monthly": "month"}.get(window.get("kind"))
            label = label or window.get("label") or window.get("id", "?")
            bar, state = quota_bar(window.get("percentRemaining"), 16 if width >= 100 else 10)
            reset = reset_time(window.get("resetsAt"), now)
            if width < 70:
                reset = reset.split(" · ", 1)[0]
            if width < 38:
                bar = bar.rsplit(" ", 1)[-1]
            cells.append((f"{label}  {bar}  ↻ {reset}", state))
        # Keep one account row when it fits; otherwise stack its quota windows.
        combined = f"{name:<12} " + "  │  ".join(text for text, _ in cells)
        if len(combined) <= width:
            rows.append((combined, max(state for _, state in cells)))
        else:
            rows.append((name, 4))
            for text, state in cells:
                if len(text) + 2 <= width:
                    rows.append(("  " + text, state))
                else:
                    quota, reset = text.split("  ↻ ", 1)
                    rows.extend([("  " + quota, state), ("    ↻ " + reset, 0)])
        rows.append(("", 0))
    if not rows:
        rows.append(("No matching accounts", 0))
    return rows


def fetch(meter):
    # The local multi-account reader supplies its credential environment.
    env = meter.quota_env(meter.DEFAULT_PROVIDERS) if hasattr(meter, "quota_env") else None
    return meter.fetch_quota(env=env)


def run_dashboard(screen, meter):
    curses.curs_set(0)
    screen.timeout(200)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        for index, color in enumerate((curses.COLOR_GREEN, curses.COLOR_YELLOW,
                                       curses.COLOR_RED, curses.COLOR_CYAN), 1):
            curses.init_pair(index, color, -1)
    data, error, updated = None, None, None
    next_fetch = 0
    future = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        while True:
            tick = time.monotonic()
            if future is None and tick >= next_fetch:
                future = pool.submit(fetch, meter)
            if future is not None and future.done():
                try:
                    result, error = future.result()
                except Exception as exc:
                    result, error = None, str(exc)
                if not error:
                    data, updated = result, tick
                next_fetch = tick + 60
                future = None
            now = datetime.now(timezone.utc)
            height, width = screen.getmaxyx()
            age = f"reading age {int(tick - updated)}s" if updated is not None else "waiting for first reading"
            activity = " · fetching…" if future is not None else f" · refresh in {max(0, math.ceil(next_fetch - tick))}s"
            rows = [("QUOTAS / REMAINING", 4),
                    (f"{now.astimezone():%H:%M:%S %Z} · {age}{activity}", 0),
                    ("─" * max(0, width - 1), 0)]
            if data is None and error is None:
                rows.append(("Reading account quotas…", 0))
            else:
                rows += dashboard_rows(data, error, meter.DEFAULT_PROVIDERS, max(1, width - 1), now)
            rows.append(("Bars: remaining % · ↻ countdown / local reset · provider reads every 60s · q quit", 0))
            screen.erase()
            for y, (text, state) in enumerate(rows[:max(0, height - 1)]):
                attr = curses.color_pair(state) if curses.has_colors() else 0
                if state == 4:
                    attr |= curses.A_BOLD
                screen.addnstr(y, 0, text, max(0, width - 1), attr)
            if len(rows) >= height and height > 1:
                screen.addnstr(height - 1, 0, "Resize taller to see all quota windows", max(0, width - 1))
            screen.refresh()
            if screen.getch() in (ord("q"), ord("Q")):
                return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meter", type=Path, default=Path(__file__).with_name("meter.py"),
                        help="Quota reader module; defaults to this project's meter.py.")
    parser.add_argument("--once", action="store_true", help="Print a single plain-text dashboard snapshot.")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("quota_reader", args.meter)
    meter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(meter)
    try:
        if args.once:
            data, error = fetch(meter)
            rows = dashboard_rows(data, error, meter.DEFAULT_PROVIDERS,
                                  shutil.get_terminal_size().columns - 1, datetime.now(timezone.utc))
            print("\n".join(text for text, _ in rows))
        else:
            curses.wrapper(run_dashboard, meter)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
