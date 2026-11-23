# WiiOS

A Wii-inspired launcher for LG webOS TVs, with customizable channels, application artwork, background music, sound effects, and remote-control navigation.

![WiiOS home screen with app channels, HDMI inputs, and system stats](docs/media/home.png)

**Minimum supported version:** webOS TV 4.0. WiiOS has been tested on a physical webOS 4.5 TV. App discovery and Home replacement depend on the firmware.

## Install from an IPK

Use this method to run WiiOS as a regular app without root.

1. Download the standard `com.wiios.launcher_<version>_all.ipk` from [GitHub Releases](https://github.com/KaykCaputo/WiiOS-webOS/releases).
2. On the TV, enable Developer Mode and turn on Key Server. Note the TV's IP address and the passphrase shown on screen. [LG Developer Mode setup](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app)
3. On a computer connected to the same network, add the TV in [webOS Dev Manager](https://github.com/webosbrew/dev-manager-desktop), install the IPK, and open **WiiOS** from the TV's app list.

## Install with the WiiOS Installer

1. Set up [Developer Mode SSH](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app) on your TV. On your computer, install Python 3.10+ and OpenSSH.
2. Download `wiios-installer.pyz` and the standard IPK from the same [GitHub release](https://github.com/KaykCaputo/WiiOS-webOS/releases). Put them in the same folder and open a terminal there.
3. Run the following command. Replace `TV_IP` with the TV's IP address and `VERSION` with the version in your IPK filename.

```sh
python3 ./wiios-installer.pyz tui --text-mode \
  --host TV_IP \
  --transport developer-mode \
  --user prisoner \
  --port 9922 \
  --ipk ./com.wiios.launcher_VERSION_all.ipk
```

4. If prompted, verify the TV's SSH host fingerprint before approving it. Use your configured SSH username and port if they differ from the example.
5. Choose **Install WiiOS as an Application** or **Update WiiOS**. Confirm with `y`, then choose **Launch WiiOS** or open it from the TV's app list.

## Install from Homebrew Channel

The catalog listing is pending. Once it is available, open [Homebrew Channel](https://repo.webosbrew.org/) on the TV, look for **WiiOS** under **Launchers**, select **Install**, then open WiiOS from the TV's app list. Until then, use the IPK steps above.

## Set WiiOS as Home with Home Chooser

The standard Home Chooser package makes WiiOS available for Home selection and uses WiiOS app discovery.

If app discovery is restricted on a rooted TV, open Home Chooser once to finish setup, then build WiiOS with `python3 scripts/build.py --home-chooser-api`. Install the IPK from `dist/home-chooser-api/`. This optional package can read the app catalog and icons through Home Chooser even when WiiOS runs as a regular app. On webOS 11 and newer, use Homebrew Channel 0.8.0 or later.

1. On a rooted LG TV, restore LG Home and disable any existing Home remaps. Install [Home Chooser](https://repo.webosbrew.org/apps/org.webosbrew.homechooser/) from Homebrew Channel and open it once to finish setup.
2. Install the WiiOS IPK from `wiios-home-chooser.zip` if your release provides it. To build it locally, run `python3 scripts/build.py --home-chooser` and install the IPK from `dist/home-chooser/` with webOS Dev Manager.
3. In WiiOS, open **Wii Options → Use WiiOS as Home** and confirm in Home Chooser. Press **Home** on the remote to try it.
4. To restore LG Home, open Home Chooser and select the LG Home option you originally used.

Both IPKs use the same app ID. Keep using the Home Chooser variant for updates. Home Chooser documents webOS 4 through 12, with Homebrew Channel 0.8.0 or later required on webOS 11 and newer. WiiOS still needs hardware validation for this integration, including startup and recovery.

For the device-specific QML integration, see the [observed compatibility and recovery notes](compatibility/profiles/observed/README.md).

CPU, RAM, and temperature require the optional WiiOS metrics helper. The WiiOS IPK measures interface FPS locally.

## Build

```sh
npm ci
npm test
python3 scripts/build.py
```

The build refreshes the IPKs, installer, and checksums in `release/`. Use the package for your installation method from that directory.

GitHub Actions publishes the standard IPK, the WiiOS Installer, the Home Chooser IPK and ZIP, and the Homebrew Channel manifest. The catalog listing is reviewed separately by the Homebrew Channel maintainers.

## License

Original source is licensed under [Apache License 2.0](LICENSE). Nintendo and LG materials remain the property of their respective owners; see [NOTICE](NOTICE). WiiOS is independent of Nintendo and LG.
