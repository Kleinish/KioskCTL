# kioskctl 0.6.0

Major backend rewrite from Python to Rust. Existing YAML and management routes are retained. Adds a versioned external-plugin protocol, permission grants, atomic config writes, constant-time token checks, native diagnostics, CI/release workflows, and rollback documentation.

The v0.5.2 Immich fixes remain requirements: originals for browser-native formats, full-size compatible derivatives for HEIC/RAW, explicit contain/cover geometry, hidden loading label, and immediate preview refresh.

Test one kiosk before fleet rollout and retain the timestamped v0.5.2 backup until all hardware behavior is verified.
