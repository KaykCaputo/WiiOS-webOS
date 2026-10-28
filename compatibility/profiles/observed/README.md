# Observed device references

These records reproduce diagnostic observations from real devices. They are not compatibility allowlist entries and must never be used by `load_verified()` to authorize a new Home replacement.

A reference marked `DETECTION_ONLY` establishes that the installer identified an already-installed, owned Home integration in a read-only report. It does not establish an independent recovery rehearsal, physical-button behavior, cold-boot stability, or cross-firmware compatibility.

References contain no TV IP address, account name, SSH host fingerprint, serial number, or secret. The reference's SHA-256 detects accidental changes to the JSON; it is not a signature or independent evidence of authenticity.
