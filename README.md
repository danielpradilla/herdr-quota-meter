# Herdr quota meter

A local Herdr plugin wrapper around [`quota-axi`](https://github.com/kunchenguid/quota-axi). It can open a live quota pane and prepare a command for Herdr's right side of the tab bar.

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

The project includes `providers.txt` with `claude,codex,copilot,commandcode`, matching the providers in your current Herdr tab-bar command. On first setup, the action copies it into Herdr's persistent plugin config directory; later runs preserve that per-user file. Edit the copy returned by `herdr plugin config-dir quota-meter` to change the display; use `all` for every provider supported by quota-axi 0.1.55. Its provider IDs are `claude`, `codex`, `cursor`, `copilot`, `grok`, `kimi`, `zai`, `agy`, `alibaba`, `opencode-go`, `commandcode`, `minimax`, `mimo`, `deepseek`, `openrouter`, `elevenlabs`, `devin`, and `muse`. New provider implementations come from quota-axi; update `QUOTA_AXI_VERSION` and this ID list when a later release adds providers.

## Data and credentials

The meter does not itself read or write credentials, and does not relay OMP's Command Code key from `~/.omp/agent/agent.db`. It passes inherited environment variables to quota-axi, which may read provider credential files or secure stores and may delegate a refresh to a provider's own CLI under its documented conditions. No credentials are written into plugin files. Review quota-axi's [safety guarantees](https://github.com/kunchenguid/quota-axi#safety-guarantees) and provider-specific behavior before use.

## Remove

Remove the tab-bar entry from `~/.config/herdr/config.toml`, then run `herdr server reload-config`. Unregister a local checkout with `herdr plugin unlink quota-meter`; for a GitHub-installed copy, use `herdr plugin uninstall quota-meter`. Neither command removes the user's Herdr config entry.
