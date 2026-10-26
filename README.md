# Herdr quota meter

Show your remaining AI subscription quotas in Herdr, either in a pane or in the top-right tab bar. The meter uses [`quota-axi`](https://github.com/kunchenguid/quota-axi) to read quotas with your existing local provider sign-ins. It reads Kiro separately through `kiro-cli`, and OpenCode Go from the credential opencode itself stores.

![Live Herdr tab bar with the quota meter](assets/herdr-quota-status.png)

## Requirements

- Herdr 0.9.1 or newer.
- Python 3 and Node.js 22.19 or newer, including `npx`. The meter downloads and runs `quota-axi@0.1.55` through `npx`.
- Sign in to the providers you want to track on the same machine and as the same user that runs Herdr. Selecting a provider does not sign you in.
- Herdr plugin commands run as the local user and are not sandboxed. Review the manifest and scripts before installing.

## 1. Install the plugin

Install the published plugin from GitHub:

```sh
herdr plugin install danielpradilla/herdr-quota-meter
```

For local development from a checkout, link it instead:

```sh
herdr plugin link /absolute/path/to/herdr-quota-meter
```

## 2. Connect your existing provider sign-ins

You do not need to copy tokens into the plugin. The meter reuses the local sign-ins that `quota-axi` supports.

| Provider | ID to use in the meter | Local sign-in source |
| --- | --- | --- |
| Claude Code | `claude` | Claude Code credentials or macOS Keychain. The default credential file is `~/.claude/.credentials.json`. |
| Codex | `codex` | Codex login in `~/.codex/auth.json`, supported Pi sign-ins, or the Codex CLI. |
| GitHub Copilot | `copilot` | Copilot `apps.json`, the Copilot CLI secure store on macOS, or a token in the GitHub CLI's `hosts.yml`. A GitHub CLI login alone does not guarantee access. |
| Cursor | `cursor` | Cursor editor sign-in or supported `cursor-agent` credentials. |
| Kiro | `kiro` | `kiro-cli` installed on `PATH` and signed in with `kiro-cli login`. |
| OpenCode Go | `opencode-go` | An opencode 2.x sign-in to OpenCode Console (`opencode auth login opencode`), read from `~/.local/share/opencode/opencode.db`. `OPENCODE_DB` and `XDG_DATA_HOME` are honored. |

For other providers and custom credential locations, see the [provider documentation for quota-axi 0.1.55](https://unpkg.com/quota-axi@0.1.55/README.md).

Inspect which sign-ins quota-axi can find without printing secret values:

```sh
npx --yes --package=quota-axi@0.1.55 quota-axi auth
```

This command does not inspect Kiro or OpenCode Go. If you use Kiro, sign in through `kiro-cli` separately; if you use OpenCode Go, sign in through `opencode auth login opencode`.

If a provider needs secure-store access, run this in an interactive terminal. Replace the provider list with your own quota-axi provider IDs:

```sh
npx --yes --package=quota-axi@0.1.55 quota-axi --provider claude,copilot --allow-keychain-prompt
```

Review and approve the access request yourself. On macOS, quota-axi documents using "Always Allow" for later background reads. The meter does not request approval itself. Do not include `kiro` or `opencode-go` in quota-axi commands: the meter reads those two itself.

The meter inherits its process environment. If your setup uses custom locations such as `CLAUDE_CONFIG_DIR` or `CODEX_HOME`, Herdr must receive those variables too. Variables set only in another terminal do not reach an already-running Herdr process.

## 3. Open the quota pane

```sh
herdr plugin pane open --plugin quota-meter --entrypoint quota
```

The pane refreshes every 60 seconds and requests all supported providers. Kiro is included only when `kiro-cli` is on `PATH`; OpenCode Go whenever an opencode sign-in is stored. This is not a scan of Herdr's configured agents: quota-axi uses its own supported local sign-in sources.

The provider list for the tab bar is separate. Follow the next section to show only the providers you use.

## 4. Choose providers for the tab bar

First, prepare the status command and find its persistent configuration directory:

```sh
herdr plugin action invoke quota-meter.configure-status --plugin quota-meter
herdr plugin log list --plugin quota-meter
herdr plugin config-dir quota-meter
```

Open `providers.txt` inside the directory returned by the last command. On first setup, it contains:

```text
claude,codex,copilot,kiro,opencode-go
```

Replace that line with the IDs of the providers you use, separated by commas. For example, for Claude Code and Codex:

```text
claude,codex
```

Use `claude,codex,cursor` to include Cursor, or `all` to request every supported provider, plus Kiro when installed and OpenCode Go when signed in. Adding an ID only selects that provider. Its local sign-in must still be available.

Now run the setup action again to generate a command with your chosen providers:

```sh
herdr plugin action invoke quota-meter.configure-status --plugin quota-meter
herdr plugin log list --plugin quota-meter
```

Copy the latest printed `[[ui.tab_bar_right]]` block into the `[ui]` section of `~/.config/herdr/config.toml`. Keep it before any subsequent non-`ui` table. If you already have a quota-meter block, replace it instead of adding a duplicate. Then validate and apply the configuration:

```sh
herdr config check
herdr server reload-config
```

The meter refreshes every 60 seconds. It shows percent remaining, with `/5h`, `/7d`, or `/30d` labels for session, weekly, or monthly quotas. `/30d` is a display label, not an exact month length.

After changing providers, repeat the setup action, replace the command block, and reload Herdr. The generated command contains the provider list. It does not read `providers.txt` on each refresh. Later setup runs preserve your saved provider list.

Herdr plugin v1 cannot add native tab-bar items from a manifest. The setup action copies `meter.py` to the persistent plugin configuration directory and prints the block. It does not edit Herdr's configuration or reload it.

## Troubleshoot missing quotas

From a checkout, test your selected providers with a single read:

```sh
python3 meter.py --line --providers claude,codex
```

Replace `claude,codex` with your provider list. To keep a detailed pane open in that terminal, omit `--line`. Press Ctrl+C to stop it.

| Display or problem | What to do |
| --- | --- |
| `auth?` | Sign in through the provider's own CLI or app, then rerun the meter. |
| `key?` | Inspect the detailed pane or `quota-axi auth`. Grant access interactively if required. A GitHub CLI token stored only in its keyring is not a supported `hosts.yml` token source. |
| `env?` | Inspect the detailed error and the upstream provider documentation for an unsupported credential selection. |
| `err?`, `NA`, or `no data` | Inspect the detailed pane or run quota-axi with `--provider YOUR_IDS --json` for the provider's error. Read Kiro through `kiro-cli` instead. |
| Works in a terminal, but not in Herdr | Make sure that Herdr can find Python, Node.js, `npx`, and any required provider CLI on its `PATH`. Compare the credential-location environment variables too. |
| Tab bar still shows the old providers | Regenerate the status command, replace the existing block, and reload Herdr as described above. |

`providers.txt` controls the generated tab-bar command only. It does not change the plugin pane's `--all` selection or the reset dashboard's default provider list.

New quota-axi provider implementations require a version that supports them. This project pins `QUOTA_AXI_VERSION` in `meter.py` to `0.1.55`.

## Optional: Quotas tab with reset countdowns

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


## Kiro

quota-axi does not support Kiro, so the meter reads it itself through the official [`kiro-cli`](https://kiro.dev) binary (`kiro-cli chat --no-interactive /usage`). It shows the month's credit allowance as `kiro 98%/30d`. Requirements and behavior:

- `kiro-cli` must be on `PATH` and logged in (`kiro-cli login`). `--all` includes Kiro only when `kiro-cli` is installed.
- A successful reading is cached in `~/.cache/herdr-quota-meter/kiro.json` for 300 seconds (override with `QUOTA_METER_KIRO_MAX_AGE`), because each read spawns `kiro-cli`.
- Every `kiro-cli chat` call saves an empty session. The meter runs it from `~/.cache/herdr-quota-meter/kiro-cwd` and afterwards deletes only zero-message sessions in that directory, so your project session lists are untouched.
- Credits used beyond the plan allowance show as `0%`.

## OpenCode Go

OpenCode Go is not read through quota-axi. opencode 2.x keeps one credential per integration and serves the Go plan from the same `opencode` (OpenCode Console) credential as Zen, while quota-axi only accepts a separate `opencode-go` credential row. The meter therefore reads the key opencode itself would use, read-only, from the `credential` table in `~/.local/share/opencode/opencode.db`, and asks `https://opencode.ai/zen/go/v1/usage` for the plan's rolling, weekly and monthly caps. It shows them as `opencode 100%/5h 100%/7d 100%/30d`.

- Sign-in: `opencode auth login opencode`. No separate Go login exists, so the Go subscription attached to that account is what these windows meter.
- The vendor reports consumption, so the meter draws what is left. A failed read shows `err?`; a missing sign-in shows `auth?`, never a full bar.
- The key is sent only to that endpoint, as a bearer token, with no cookie jar and no proxy configuration of its own.

## Data and credentials

The meter reads one credential itself: the opencode key described above, read-only and never printed or cached. Otherwise it passes inherited environment variables to quota-axi, which may read provider credential files or secure stores and may delegate a refresh to a provider's own CLI under its documented conditions. No credentials are written into plugin files. Review quota-axi's [safety guarantees](https://github.com/kunchenguid/quota-axi#safety-guarantees) and provider-specific behavior before use.

## Remove

Remove the tab-bar entry from `~/.config/herdr/config.toml`, then run `herdr server reload-config`. Unregister a local checkout with `herdr plugin unlink quota-meter`; for a GitHub-installed copy, use `herdr plugin uninstall quota-meter`. Neither command removes the user's Herdr config entry.
