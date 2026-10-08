# v0.6 development checkpoints

- [x] CP1 — Inventory v0.5.2 features, routes, config, services, and Immich fixes.
- [x] CP2 — Define Rust architecture and language-neutral plugin protocol.
- [x] CP3 — Implement Rust crate, schema migration, HTTP shell, diagnostics, and plugin host.
- [x] CP4 — Add installer, services, rollback, docs, contribution/security files, and GitHub workflows.
- [x] CP5 — Compile on x86_64 and aarch64; resolve compiler/clippy findings. Fedora, Debian, and Alpine have completed WIP8/WIP9 builds and browser-control smoke tests. WIP11 fixes systemd runtime-directory startup on Arch.
- [ ] CP6 — Hardware regression: Chromium, Wayland, touch, audio, idle, MQTT, Home Assistant. Browser/CDP, remote input, Web UI, and brightness passed on Fedora, Debian, Alpine, and Arch. WIP12 targets diagnostics, power actions, audio fallback, and display-power evidence. WIP17 adds the optional native application launcher and needs a session launch smoke test.
- [ ] CP7 — Immich regression: JPEG/PNG/WebP plus HEIC/RAW and both fit modes.
- [ ] CP8 — Tag `v0.6.0-rc.1`, pilot one kiosk, then promote after soak testing.

## Handoff

Start at CP6. The current workspace lacks a Rust compiler, so compilation must run in GitHub Actions or a Rust-equipped Linux host. The compatibility API shell, browser control, and initial display/audio providers are present; expand and exercise remaining platform operations during CP6 before a final production tag.
