# Observed device references

These records describe observations on a specific physical TV. They are not compatibility allowlist entries and must never authorize a new Home replacement through `load_verified()`.

The LG 32LM625BPSB reference remains `DETECTION_ONLY`. On 2026-11-17, its existing legacy QML integration was manually reactivated and confirmed after a cold boot. The operator confirmed WiiOS appeared and the physical Home button opened it. The startup hook had to wait for the Homebrew failsafe flag to clear before launching the boot script.

The original LG QML files were verified by their stock SHA-256 values before activation and after recovery. The bind mounts did not overwrite files in `/usr`. The trial watchdog could not unmount the busy `/tmp/checkpoint/com.webos.app.fullhome` target; a normal reboot cleared the temporary mounts and restored the original QML. Automatic rollback is therefore not qualified, and this observation does not authorize new takeovers or other devices.

References contain no TV IP address, account name, SSH host fingerprint, serial number, or secret. A reference hash detects accidental file changes; it is not a signature or independent proof.
