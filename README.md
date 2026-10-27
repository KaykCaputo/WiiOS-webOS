# WiiOS

A Wii-inspired Home screen for LG webOS TVs, featuring customizable channels, application artwork, background music, sound effects, and remote-control navigation.

![WiiOS Home Screen](docs/media/home.png)

## Installation

Download the WiiOS IPK and `wiios-installer.pyz` from the [latest release](https://github.com/KaykCaputo/WiiOS-webOS/releases/latest). Keep both files in the same directory.

The installer provides a full-screen terminal interface with separate screens for device information, firmware compatibility, installation plans, approval, progress, diagnostics, and results.

### Requirements

- Python 3.10 or newer on your computer.
- OpenSSH (`ssh`, `ssh-keygen`, and `ssh-keyscan`).
- An LG webOS TV reachable over the local network.
- An authorized Developer Mode or root SSH connection.
- A terminal with `curses` support for the full-screen TUI.

The standalone `.pyz` does not require installing Python dependencies. Linux is covered by automated installer tests; macOS and Windows require device-level validation.

### Verify the installer

Before connecting to your TV, confirm that the current installer is being executed:

```sh
python3 ./wiios-installer.pyz --version
```

Expected output for the TUI r3 release:

```text
WiiOS Installer 0.3.34-tui-r3 (2026-10-27-r3)
```

If this command reports an unknown option or requires a subcommand, replace the old `.pyz` with the latest release file. You can also run the uniquely named `wiios-installer-tui-r3.pyz` from the same release without renaming it.

### Developer Mode SSH

Follow the [official LG Developer Mode setup](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app) and configure your authorized SSH credentials.

```sh
python3 ./wiios-installer.pyz tui \
  --host TV_IP \
  --transport developer-mode \
  --user prisoner \
  --port 9922 \
  --identity DEV_KEY \
  --known-hosts "$HOME/.ssh/known_hosts" \
  --ipk ./com.wiios.launcher_0.3.34_all.ipk
```

The username and port are examples. Use the credentials configured for your TV. Omit `--identity` if an SSH agent already provides the required key.

### Root SSH

If your TV already has authorized root SSH access, use the root transport instead:

```sh
python3 ./wiios-installer.pyz tui \
  --host TV_IP \
  --transport root-ssh \
  --user root \
  --port 22 \
  --known-hosts "$HOME/.ssh/known_hosts" \
  --ipk ./com.wiios.launcher_0.3.34_all.ipk
```

Root SSH access is not required for app-only installation. The installer does not root the TV or install a rooting method.

### SSH host verification

The installer uses `~/.ssh/known_hosts` by default and requires a trusted SSH host key. If regular SSH to your TV is already configured, reuse that trust store.

If you need to register a new host key, obtain the TV's expected SHA-256 fingerprint through an independently trusted method before running:

```sh
python3 ./wiios-installer.pyz trust \
  --host TV_IP \
  --transport root-ssh \
  --user root \
  --port 22 \
  --fingerprint SHA256:VERIFIED_FINGERPRINT
```

Do not disable SSH host-key checking or approve an unexpected key change.

### Using the terminal installer

Navigate with the arrow keys and select with Enter. Use Escape to go back, and `F1` for help. When viewing a proposed installation plan, press `D` to inspect its complete details. The installer requires explicit confirmation before applying changes.

The full-screen TUI does not automatically fall back to a second, line-oriented menu. If your terminal does not support `curses`, select the text interface explicitly:

```sh
python3 ./wiios-installer.pyz tui --text-mode \
  --host TV_IP \
  --transport root-ssh \
  --user root \
  --port 22 \
  --ipk ./com.wiios.launcher_0.3.34_all.ipk
```

### Installation modes

**Home replacement is WiiOS's primary goal.** The long-term objective is to replace the original LG Home screen while preserving reliable application launching, remote navigation, startup behavior, and recovery.

- **App-only:** Installs WiiOS as a regular application without changing the original LG Home, Home hooks, metrics services, or privacy settings. It works without root when the required Developer Mode installation capabilities are available.
- **Home replacement:** Requires an exact, hardware-validated compatibility profile and an independently verified recovery procedure. New Home takeover is currently blocked on unqualified firmware. Installing the IPK alone does not replace the original Home.

Start with **Inspect Firmware Compatibility** before attempting Home integration. Compatibility reports are diagnostic evidence, not confirmation of Home replacement support.

### Updates, recovery, and troubleshooting

The installer includes options to update the application, launch WiiOS, inspect compatibility, export diagnostics, reconcile interrupted installations, and restore the original Home when a supported recovery transaction exists.

If an operation is interrupted, use **Reconcile Interrupted Installation** instead of repeatedly reinstalling the same package. For command-line recovery, use the transaction identifier shown in the diagnostic output:

```sh
python3 ./wiios-installer.pyz reconcile \
  --host TV_IP \
  --transport root-ssh \
  --user root \
  --port 22 \
  --transaction TRANSACTION_ID
```

If the terminal unexpectedly displays an old menu or `--version` is unavailable, verify the exact installer path and replace the outdated file:

```sh
realpath ./wiios-installer.pyz
python3 ./wiios-installer.pyz --version
```

See [installation details](docs/INSTALL.md), [firmware compatibility](docs/COMPATIBILITY.md), and [recovery procedures](docs/RECOVERY.md).

## Build and test

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
npm ci
npm test
python3 scripts/build.py
```

Build artifacts include the IPK, standalone terminal installer, SHA-256 checksums, and a build manifest. Host-side tests do not require a connected TV. Firmware-specific Home takeover still requires validation on physical hardware.

## License

Original source is licensed under [Apache License 2.0](LICENSE). Nintendo and LG materials remain the property of their respective owners; see [NOTICE](NOTICE). WiiOS is independent of Nintendo and LG.
