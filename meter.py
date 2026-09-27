#!/usr/bin/env python3
"""
herdr_quota_meter.py — a small self-refreshing quota readout for a Herdr pane
or tab-bar status entry.

Wraps quota-axi, a local-first CLI that reports LLM subscription quota windows from official
provider endpoints. It polls quota-axi and renders a compact box (for a
dedicated pane) or single line (for Herdr's tab_bar_right command entries).
Credential handling and any provider CLI refresh behavior belong to
quota-axi; this script never reads credentials itself.
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
import textwrap

WARN_THRESHOLD = 15  # percent remaining at/below this gets a warning marker



QUOTA_AXI_VERSION = "0.1.55"
QUOTA_AXI_TIMEOUT = 20


def fetch_quota(env=None, providers_filter=None):
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

# A status entry is narrow and read at a glance, so long provider ids get a
# short display alias. Filtering (--providers, --exclude-ids) still uses the
# full quota-axi id; only what is drawn changes.
PROVIDER_LABELS = {"commandcode": "cmd"}


def display_name(provider):
    return PROVIDER_LABELS.get(provider, provider)


# A provider quota-axi could not read still gets reported; "NA" alone hides
# whether it is signed out, waiting on a Keychain consent dialog, or simply
# returning nothing. Tags are one word because a status-bar slot is narrow.
# `state.error` is quota-axi's specific reason, `state.status` the fallback.
UNREADABLE_ERROR_TAGS = {
    "commandcode_sign_in_required": "auth?",
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
            name = display_name(p.get("provider", "?"))
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


DEFAULT_PROVIDERS = ["claude", "codex", "copilot", "commandcode"]


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
        name = display_name(p.get("provider", "?"))
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
    ap.add_argument("--all", action="store_true", help="Show every provider quota-axi supports.")
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
