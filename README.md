# Herdr quota meter

A local Herdr plugin wrapper around [`quota-axi`](https://github.com/kunchenguid/quota-axi). It can open a live quota pane and prepare a command for Herdr's right side of the tab bar.

![Live Herdr tab bar with the quota meter](assets/herdr-quota-status.png)

## Requirements

- Herdr 0.9.1 or newer.
- Python 3 and Node.js 22.19 or newer (`npx`); the meter installs/runs pinned `quota-axi@0.1.55` through npx.
- Provider CLI/account credentials already configured locally. The meter does not read or copy credentials itself. `quota-axi` reads its supported local provider sources; secure-store reads may require a separate interactive approval as described by its documentation.
- Herdr plugin commands run as the local user and are not sandboxed. Review the manifest and scripts before installing.

## Install and open the pane

Install the published plugin from GitHub and open its pane:

```sh
herdr plugin install danielpradilla/herdr-quota-meter
herdr plugin pane open --plugin quota-meter --entrypoint quota
```

For local development from a checkout, link it instead:

```sh
herdr plugin link /absolute/path/to/herdr-quota-meter
herdr plugin pane open --plugin quota-meter --entrypoint quota
```

To list it in Herdr's marketplace, add the `herdr-plugin` topic to the GitHub repository.

The pane refreshes every 60 seconds. It defaults to all providers. It invokes quota-axi with `--json`; provider requests follow quota-axi's documented read behavior and local authentication setup.

## Quotas tab: reset times

`reset_tab.py` is a standard-library curses dashboard: horizontal bars show
remaining quota on a fixed 0–100% scale, with one countdown per quota window
and its local reset date/time. Countdowns tick in seconds and stop at zero;
zero never implies the provider has replenished its quota.

Accounts stay on one row when space allows; narrow terminals stack their
windows. Bars use green above 30%, yellow at 16–30%, and red at 15% or below.
Unknown remaining quota uses question marks, not an empty bar. Missing reset
timestamps appear as `reset unknown`; the viewer never guesses them.

Provider reads run in the background every 60 seconds, so countdowns keep
ticking during network calls. The header shows reading age and refresh state;
a failed refresh labels the retained last successful quotas as stale.
The main tab-bar status is unchanged.

From a checkout, create a tab in your current workspace:

```sh
herdr tab create --workspace "$HERDR_WORKSPACE_ID" --cwd "$PWD" --label Quotas --no-focus
```

Use the returned `root_pane.pane_id` as `<pane-id>` to start the viewer:

```sh
herdr pane run <pane-id> "python3 '$PWD/reset_tab.py'"
```

Click the Quotas tab to view it; `q` or Ctrl+C stops the dashboard. No new
global shortcut or custom Herdr build is needed. `--once` prints a plain-text
snapshot. Python must include curses support (standard on macOS/Linux).

By default, the viewer uses this checkout's `meter.py` and its default provider
list. `--meter /absolute/path/to/reader.py` reuses a customized local reader
without copying credentials or changing the installed status command. The reader
must expose `DEFAULT_PROVIDERS` and `fetch_quota(env=None)` returning
`(data, error)` in the meter's provider/window schema; an optional
`quota_env(providers)` supplies its existing credential environment. Named
accounts in that data remain separate rows. Run the focused regression check
with `python3 -m unittest test_reset_tab`.

## Show the meter in the top-right tab bar

Herdr plugin v1 does not let a manifest add native tab-bar items. Invoke the plugin action; it copies `meter.py` into the plugin's persistent config directory and prints the config stanza to the plugin command log:

```sh
herdr plugin action invoke quota-meter.configure-status --plugin quota-meter
herdr plugin log list --plugin quota-meter
```

Copy the printed `[[ui.tab_bar_right]]` block under your existing `[ui]` configuration in `~/.config/herdr/config.toml`, then validate and apply it yourself:

```sh
herdr config check
herdr server reload-config
```

The project includes `providers.txt` with `claude,codex,copilot,kiro`. On first setup, the action copies it into Herdr's persistent plugin config directory; later runs preserve that per-user file. Edit the copy returned by `herdr plugin config-dir quota-meter` to change the display; use `all` for every provider supported by quota-axi 0.1.55. See quota-axi's documentation for supported provider IDs. New provider implementations come from quota-axi; update `QUOTA_AXI_VERSION` when adopting a later release.

## Kiro

quota-axi does not support Kiro, so the meter reads it itself through the official [`kiro-cli`](https://kiro.dev) binary (`kiro-cli chat --no-interactive /usage`). It shows the month's credit allowance as `kiro 98%/30d`. Requirements and behavior:

- `kiro-cli` must be on `PATH` and logged in (`kiro-cli login`). `--all` includes Kiro only when `kiro-cli` is installed.
- A successful reading is cached in `~/.cache/herdr-quota-meter/kiro.json` for 300 seconds (override with `QUOTA_METER_KIRO_MAX_AGE`), because each read spawns `kiro-cli`.
- Every `kiro-cli chat` call saves an empty session. The meter runs it from `~/.cache/herdr-quota-meter/kiro-cwd` and afterwards deletes only zero-message sessions in that directory, so your project session lists are untouched.
- Credits used beyond the plan allowance show as `0%`.

## Data and credentials

The meter does not itself read or write credentials. It passes inherited environment variables to quota-axi, which may read provider credential files or secure stores and may delegate a refresh to a provider's own CLI under its documented conditions. No credentials are written into plugin files. Review quota-axi's [safety guarantees](https://github.com/kunchenguid/quota-axi#safety-guarantees) and provider-specific behavior before use.

## Remove

Remove the tab-bar entry from `~/.config/herdr/config.toml`, then run `herdr server reload-config`. Unregister a local checkout with `herdr plugin unlink quota-meter`; for a GitHub-installed copy, use `herdr plugin uninstall quota-meter`. Neither command removes the user's Herdr config entry.
