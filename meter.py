#!/usr/bin/env python3
"""
herdr_quota_meter.py — a small self-refreshing quota readout for a Herdr pane
or tab-bar status entry.

Wraps quota-axi, a local-first CLI that reports LLM subscription quota windows from official
provider endpoints. It polls quota-axi and renders a compact box (for a
dedicated pane) or single line (for Herdr's tab_bar_right command entries).
Credential handling and any provider CLI refresh behavior belong to
quota-axi; this script never reads credentials itself.

Kiro is not a quota-axi provider, so it is read separately through the
official `kiro-cli` binary's `/usage` command (see fetch_kiro).
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
import textwrap

WARN_THRESHOLD = 15  # percent remaining at/below this gets a warning marker



QUOTA_AXI_VERSION = "0.1.55"
QUOTA_AXI_TIMEOUT = 20


KIRO_PROVIDER = "kiro"
KIRO_CLI = "kiro-cli"
KIRO_USAGE_TIMEOUT = 12
KIRO_CLEANUP_TIMEOUT = 5
# Whole Kiro read (usage + session cleanup) stays inside this budget so the
# meter finishes within Herdr's status-command timeout (25s by default).
KIRO_BUDGET = 18
# Kiro credits move slowly and each read spawns kiro-cli (~3s), so a
# successful reading is reused for this many seconds.
KIRO_MAX_AGE = int(os.environ.get("QUOTA_METER_KIRO_MAX_AGE", "300"))
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "herdr-quota-meter"
KIRO_CACHE = CACHE_DIR / "kiro.json"
# `kiro-cli chat` saves an (empty) session per invocation, scoped to its cwd.
# Running it from a dedicated directory keeps those out of real project
# session lists and lets cleanup delete them without touching anything else.
KIRO_WORKDIR = CACHE_DIR / "kiro-cwd"

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# e.g. "Credits (12.60 of 1000 covered in plan), 1.3%"
KIRO_CREDITS_RE = re.compile(r"Credits\s*\(\s*([\d.,]+)\s+of\s+([\d.,]+)\s+covered in plan\s*\)", re.I)
# e.g. "Estimated Usage | resets on 2026-11-01 | KIRO PRO"
KIRO_RESET_RE = re.compile(r"resets on\s+(\d{4}-\d{2}-\d{2})", re.I)


def _num(text):
    return float(text.replace(",", ""))


def parse_kiro_usage(text):
    """Turn `kiro-cli chat --no-interactive /usage` output into a provider
    entry shaped like quota-axi's, so render/render_line need no special case."""
    text = ANSI_RE.sub("", text)
    provider = {"provider": KIRO_PROVIDER, "state": {}, "windows": []}
    m = KIRO_CREDITS_RE.search(text)
    if not m:
        lowered = text.lower()
        if "login" in lowered or "log in" in lowered or "not logged" in lowered:
            provider["state"] = {"status": "auth_required", "remedyCommand": "kiro-cli login"}
        else:
            snippet = " ".join(text.split())[:80] or "empty /usage output"
            provider["state"] = {"status": "error", "error": f"unparsed kiro usage: {snippet}"}
        return provider

    used, limit = _num(m.group(1)), _num(m.group(2))
    remaining = max(0.0, 100.0 - used / limit * 100.0) if limit > 0 else 0.0
    window = {
        "id": "credits",
        "kind": "monthly",
        "label": "credits",
        "percentRemaining": round(remaining),
        "used": used,
        "limit": limit,
    }
    r = KIRO_RESET_RE.search(text)
    if r:
        window["resetsAt"] = f"{r.group(1)}T00:00:00Z"
    provider["state"] = {"status": "ok"}
    provider["windows"] = [window]
    return provider


def _cleanup_kiro_sessions(deadline):
    """Delete the empty sessions our /usage calls left in KIRO_WORKDIR. Only
    sessions with zero messages in that dedicated cwd are removed. Stops at
    `deadline`; anything left over is removed on a later run."""
    def time_left():
        return deadline - time.monotonic() >= KIRO_CLEANUP_TIMEOUT

    if not time_left():
        return
    try:
        proc = subprocess.run(
            [KIRO_CLI, "chat", "--list-sessions", "--format", "json"],
            cwd=KIRO_WORKDIR, capture_output=True, text=True, timeout=KIRO_CLEANUP_TIMEOUT,
        )
        envelopes = json.loads(proc.stdout)
    except Exception:
        return
    ids = [
        s.get("sessionId")
        for env in envelopes if env.get("cwd") == str(KIRO_WORKDIR)
        for s in env.get("sessions", [])
        if s.get("messageCount") == 0 and s.get("sessionId")
    ]
    for sid in ids:
        if not time_left():
            return
        try:
            subprocess.run(
                [KIRO_CLI, "chat", "--delete-session", sid],
                cwd=KIRO_WORKDIR, capture_output=True, timeout=KIRO_CLEANUP_TIMEOUT,
            )
        except Exception:
            return


def fetch_kiro():
    """Read Kiro credit usage via the official CLI. Always returns a provider
    entry; failures are reported through its state like quota-axi does."""
    try:
        cached = json.loads(KIRO_CACHE.read_text(encoding="utf-8"))
        if time.time() - cached.get("fetchedAt", 0) < KIRO_MAX_AGE:
            return cached["provider"]
    except Exception:
        pass

    if not shutil.which(KIRO_CLI):
        return {"provider": KIRO_PROVIDER, "windows": [],
                "state": {"status": "unavailable", "error": "kiro-cli not found on PATH"}}
    deadline = time.monotonic() + KIRO_BUDGET
    try:
        KIRO_WORKDIR.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [KIRO_CLI, "chat", "--no-interactive", "/usage"],
            cwd=KIRO_WORKDIR, capture_output=True, text=True,
            timeout=KIRO_USAGE_TIMEOUT, stdin=subprocess.DEVNULL,
        )
        provider = parse_kiro_usage(proc.stdout + "\n" + proc.stderr)
    except Exception as e:
        provider = {"provider": KIRO_PROVIDER, "windows": [],
                    "state": {"status": "error", "error": f"kiro-cli failed: {e}"[:120]}}
    finally:
        if KIRO_WORKDIR.is_dir():
            _cleanup_kiro_sessions(deadline)

    if provider["state"].get("status") == "ok":
        try:
            KIRO_CACHE.write_text(json.dumps({"fetchedAt": time.time(), "provider": provider}), encoding="utf-8")
        except Exception:
            pass
    return provider


def fetch_quota(env=None, providers_filter=None):
    """Fetch quota-axi providers and, when requested, Kiro, in parallel.
    providers_filter=None means "all": every quota-axi provider plus Kiro if
    kiro-cli is installed."""
    if providers_filter is None:
        want_kiro = shutil.which(KIRO_CLI) is not None
        axi_filter, want_axi = None, True
    else:
        want_kiro = KIRO_PROVIDER in providers_filter
        axi_filter = [p for p in providers_filter if p != KIRO_PROVIDER]
        want_axi = bool(axi_filter)

    with ThreadPoolExecutor(max_workers=2) as pool:
        kiro_future = pool.submit(fetch_kiro) if want_kiro else None
        if want_axi:
            data, error = fetch_quota_axi(env=env, providers_filter=axi_filter)
        else:
            data, error = {"providers": []}, None
        kiro = kiro_future.result() if kiro_future else None

    if error or kiro is None:
        return data, error
    providers = list(data.get("providers", []))
    # Keep the user's requested order (e.g. --providers kiro,codex).
    order = providers_filter or []
    idx = order.index(KIRO_PROVIDER) if KIRO_PROVIDER in order else len(providers)
    after = set(order[idx + 1:])
    insert_at = next((i for i, p in enumerate(providers) if p.get("provider") in after), len(providers))
    providers.insert(insert_at, kiro)
    return {**data, "providers": providers}, None


def fetch_quota_axi(env=None, providers_filter=None):
    command = [
        "npx", "--yes", f"--package=quota-axi@{QUOTA_AXI_VERSION}",
        "quota-axi", "--json",
    ]
    if providers_filter:
        command.extend(["--provider", ",".join(providers_filter)])
    try:
        proc = subprocess.run(
            command,
            capture_output=True, text=True, timeout=QUOTA_AXI_TIMEOUT, env=env,
        )
    except Exception as e:
        return None, f"quota-axi failed to run: {e}"
    if proc.returncode != 0:
        return None, f"quota-axi exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:200]}"
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as e:
        return None, f"could not parse quota-axi output: {e}"

def fmt_relative(iso_ts):
    if not iso_ts:
        return ""
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return ""
    delta = dt - datetime.now(timezone.utc)
    secs = int(delta.total_seconds())
    if secs <= 0:
        return "now"
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{mins}m"
    return f"{mins}m"


INNER = 32  # visible content width between the two box-drawing borders

# A provider quota-axi could not read still gets reported; "NA" alone hides
# whether it is signed out, waiting on a Keychain consent dialog, or simply
# returning nothing. Tags are one word because a status-bar slot is narrow.
# `state.error` is quota-axi's specific reason, `state.status` the fallback.
UNREADABLE_ERROR_TAGS = {
    "keychain_prompt_required": "key?",
    "keychain_prompt_timeout": "key?",
    "credentials_keyring_storage": "key?",
    "environment_selection_unsupported": "env?",
}
UNREADABLE_STATUS_TAGS = {
    "auth_required": "auth?",
    "unavailable": "err?",
    "error": "err?",
}


def unreadable_tag(state):
    if state.get("error") in UNREADABLE_ERROR_TAGS:
        return UNREADABLE_ERROR_TAGS[state["error"]]
    return UNREADABLE_STATUS_TAGS.get(state.get("status"))


def _wrap(text, indent="  "):
    """Wrap an over-long row (a remedy command) instead of letting _row cut it
    off: a remedy that cannot be read cannot be run. Width is INNER - 1 because
    _row prepends one space."""
    return textwrap.wrap(
        text, width=INNER - 1, initial_indent=indent, subsequent_indent=indent
    )


def _row(text=""):
    text = " " + text
    if len(text) > INNER:
        text = text[: INNER - 1] + "…"
    return "│" + text.ljust(INNER) + "│"


def render(data, error, providers_filter=None):
    lines = ["┌" + "─ quota ".ljust(INNER, "─") + "┐"]

    if error:
        lines.append(_row(error))
    else:
        providers = data.get("providers", [])
        if providers_filter:
            providers = [p for p in providers if p.get("provider") in providers_filter]
        if not providers:
            lines.append(_row("no matching providers"))

        for p in providers:
            name = p.get("provider", "?")
            state = p.get("state", {})

            tag = unreadable_tag(state)
            if tag:
                lines.append(_row(f"{name:<7} {tag}"))
                reason = state.get("error")
                if reason and reason != "auth_required":
                    lines.extend(_row(row) for row in _wrap(reason))
                lines.extend(_row(row) for row in _wrap(state.get("remedyCommand") or ""))
                continue

            windows = p.get("windows", [])
            if not windows:
                lines.append(_row(f"{name:<8} no data"))
                continue

            for w in windows:
                pct = w.get("percentRemaining")
                label = w.get("label", w.get("id", "?"))
                resets_in = fmt_relative(w.get("resetsAt"))
                pct_str = f"{pct:>3}%" if isinstance(pct, (int, float)) else "  ?%"
                mark = "⚠" if isinstance(pct, (int, float)) and pct <= WARN_THRESHOLD else " "
                stale = " (stale)" if state.get("stale") else ""
                row = f"{name:<7} {pct_str}{mark} {label}"
                if resets_in:
                    row += f" rst {resets_in}"
                lines.append(_row(row + stale))

    lines.append(_row(f"updated {datetime.now().strftime('%H:%M:%S')}"))
    lines.append("└" + "─" * INNER + "┘")
    return "\n".join(lines)


DEFAULT_PROVIDERS = ["claude", "codex", "copilot", "kiro"]


# Default: show every window kind a provider reports, no filtering.
DEFAULT_WINDOW_KINDS = []

# Display order and short label per window `kind`. "session"/"weekly"
# durations are fixed and documented by quota-axi (18,000s / 604,800s).
# "monthly" has no fixed duration — quota-axi deliberately never invents
# one because months vary in length — so "30d" here is a conventional
# approximation for the label only, never used in any calculation.
KIND_ORDER = {"session": 0, "weekly": 1, "monthly": 2}
KIND_LABELS = {
    "session": "5h",
    "weekly": "7d",
    "monthly": "30d",
}


def render_line(data, error, providers_filter=None, window_kinds=DEFAULT_WINDOW_KINDS, exclude_ids=None):
    """Compact single-line rendering for a status-bar slot (e.g. Herdr's
    tab_bar_right 'command' entry), as opposed to the boxed pane view.

    Each provider reports a `kind` per window (e.g. "session", "weekly",
    "monthly") straight from quota-axi. By default every window a provider
    reports is shown, each labeled with its kind (e.g. "71%/5h 91%/7d") so
    nothing is hidden or picked for you; pass `window_kinds` to restrict to
    specific kinds. Some providers (e.g. Copilot) report several distinct
    windows sharing one `kind` (chat/completions/premium_interactions are
    all "monthly") — `exclude_ids` hides specific windows by their exact
    `id`, which is the only field that actually distinguishes them."""
    if error:
        return f"quota: {error}"[:60]

    providers = data.get("providers", [])
    if providers_filter:
        providers = [p for p in providers if p.get("provider") in providers_filter]
    if not providers:
        return "quota: NA"

    parts = []
    for p in providers:
        name = p.get("provider", "?")
        state = p.get("state", {})
        tag = unreadable_tag(state)
        if tag:
            parts.append(f"{name} {tag}")
            continue
        windows = p.get("windows", [])
        if window_kinds:
            windows = [w for w in windows if w.get("kind") in window_kinds]
        if exclude_ids:
            windows = [w for w in windows if w.get("id") not in exclude_ids]
        if not windows:
            parts.append(f"{name} NA")
            continue
        windows = sorted(windows, key=lambda w: KIND_ORDER.get(w.get("kind"), 99))
        pieces = []
        for w in windows:
            pct = w.get("percentRemaining")
            pct_str = f"{pct:.0f}%" if isinstance(pct, (int, float)) else "?%"
            mark = "⚠" if isinstance(pct, (int, float)) and pct <= WARN_THRESHOLD else ""
            label = KIND_LABELS.get(w.get("kind"), w.get("kind", "?"))
            pieces.append(f"{pct_str}{mark}/{label}")
        parts.append(f"{name} " + " ".join(pieces))
    return " | ".join(parts)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interval", type=int, default=60, help="Refresh interval in seconds, for --loop (default: 60).")
    ap.add_argument("--all", action="store_true", help="Show every provider quota-axi supports, plus Kiro if kiro-cli is installed.")
    ap.add_argument("--providers", help="Comma-separated provider list to show (overrides --all/default).")
    ap.add_argument("--line", action="store_true", help="Print one compact line instead of a box (for a status-bar slot).")
    ap.add_argument("--loop", action="store_true", help="Keep refreshing (the boxed pane view always loops; --line defaults to a single one-shot print unless this is set).")
    ap.add_argument("--window", default="", help="Comma-separated window kinds to show in --line mode (e.g. weekly,monthly). Default: show every kind the provider reports. Ignored in box mode, which always shows every window.")
    ap.add_argument("--exclude-ids", default="", help="Comma-separated window ids to hide in --line mode (e.g. chat,completions), for providers that report several windows sharing one kind.")
    args = ap.parse_args()

    window_kinds = [w.strip() for w in args.window.split(",") if w.strip()]
    exclude_ids = [w.strip() for w in args.exclude_ids.split(",") if w.strip()]

    if args.providers:
        providers_filter = [p.strip() for p in args.providers.split(",") if p.strip()]
    elif args.all:
        providers_filter = None
    else:
        providers_filter = DEFAULT_PROVIDERS

    def emit():
        data, error = fetch_quota(providers_filter=providers_filter)
        if args.line:
            print(render_line(data, error, providers_filter, window_kinds, exclude_ids))
        else:
            print(render(data, error, providers_filter))

    if args.line and not args.loop:
        emit()
        return

    try:
        while True:
            if not args.line:
                sys.stdout.write("\x1b[2J\x1b[H")  # clear screen, home cursor
            emit()
            sys.stdout.flush()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
