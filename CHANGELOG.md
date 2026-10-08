# Changelog

## Unreleased

- Added `launcher` configuration for running a native/local graphical application in the kiosk session instead of Chromium.
- Removed an unused `uuid` dependency so Rust 1.88 builds do not resolve a newer unsupported release.

## 0.6.0 — release candidate worktree

- Replaced the Python management-agent foundation with a Tokio/Axum Rust crate.
- Added schema-11 migration, atomic config saves, secret redaction, and constant-time API authentication.
- Added an external JSON-RPC plugin protocol and sample Rust plugin.
- Retained the v0.5.2 management UI and compatibility route names.
- Added systemd/OpenRC packaging, rollback, CI, cross-architecture release jobs, and operator/developer documentation.

See `docs/RELEASE-0.6.0.md` and `CHECKPOINTS.md` for validation still required before the final tag.
