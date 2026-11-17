# WiiOS

A Wii-inspired launcher for LG webOS TVs, with customizable channels, application artwork, background music, sound effects, and remote-control navigation.

## Install

Download the WiiOS `.ipk` and `wiios-installer.pyz` from the [latest release](https://github.com/KaykCaputo/WiiOS-webOS/releases/latest) and keep them in the same directory. Python 3.10+ and OpenSSH are required on the computer.

For a regular app installation over Developer Mode SSH:

```sh
python3 ./wiios-installer.pyz tui --text-mode \
  --host TV_IP \
  --transport developer-mode \
  --user prisoner \
  --port 9922 \
  --ipk ./com.wiios.launcher_VERSION_all.ipk
```

Use the username and port configured for Developer Mode. The installer requires a trusted SSH host key. Root SSH is optional for app-only installation.

## Home replacement

An IPK installation does not replace LG Home. New Home takeovers remain blocked unless the exact device profile and recovery path are release-qualified. The existing legacy QML integration is device-specific and is not installed by the regular app installer. See [observed compatibility notes](compatibility/profiles/observed/README.md).

The legacy QML integration uses temporary bind mounts and preserves the original LG files. If its rollback reports a busy checkpoint, do not force or lazy-unmount it; a normal TV reboot clears the mounts and restores the original Home.

## Build

```sh
npm ci
npm test
python3 scripts/build.py
```

The build creates the IPK, standalone installer, checksums, and build manifest. Host tests do not prove compatibility with additional TV models or firmware.

## License

Original source is licensed under [Apache License 2.0](LICENSE). Nintendo and LG materials remain the property of their respective owners; see [NOTICE](NOTICE). WiiOS is independent of Nintendo and LG.
