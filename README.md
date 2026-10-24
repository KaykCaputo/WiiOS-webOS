# WiiOS — Wii-Inspired Launcher for LG webOS TVs

WiiOS is an open-source, Nintendo Wii-inspired home screen launcher for rooted LG smart TVs running webOS.

It features customizable Wii-style channels, automatic app discovery, dynamic artwork, and Home button integration.

**Compatibility:** Tested on LG LM625BPSB running webOS 4.5.

[Download Latest Release](https://github.com/KaykCaputo/WiiOS-webOS/releases/latest)

## Preview

![WiiOS Home Screen](docs/media/home.png)

### Demo

![WiiOS Interface Demo](docs/media/demo.gif)

## Installation

Full Home integration requires a rooted LG webOS TV with Homebrew Channel and SSH root access. Python 3 and Make are required on your computer.

**Install WiiOS and Home integration:**

```sh
make install TV=YOUR_TV_IP
```

**Update the launcher and its local artwork service:**

```sh
make app TV=YOUR_TV_IP
```

**Build the IPK without modifying the TV:**

```sh
make build
```

The IPK can run as a standalone application without root. Automatic artwork discovery and Home replacement require elevated access.

**Warning:** Home integration is firmware-specific. Do not apply it to untested TV models or firmware versions.

## Commands

The following commands accept `TV=YOUR_TV_IP`:

- `make status` — Check WiiOS status.
- `make home` — Enable Home integration.
- `make home-off` — Disable Home integration.
- `make privacy` — Enable privacy features.
- `make privacy-off` — Disable privacy features.
- `make off` — Disable WiiOS integration.

Run tests with:

```sh
npm ci && make test
```

## License

Original WiiOS source code is licensed under [Apache License 2.0](LICENSE).

Nintendo Wii trademarks, interface materials, graphics, music, and sound effects belong to Nintendo and/or their respective owners and are not covered by the code license.

See [NOTICE](NOTICE) for additional information.

WiiOS is an independent project and is not affiliated with Nintendo or LG.
