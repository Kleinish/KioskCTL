# Architecture

The `kioskctl` binary has four layers: Axum HTTP management/API, configuration and migrations, Linux/Chromium adapters, and plugins. Shared state uses Tokio read/write locks. Operating-system work is delegated to bounded child processes.

The root agent owns configuration and service management. The graphical browser runs as the unprivileged `kioskctl` user. External plugins are separate executables and receive requests on standard input; no unstable Rust ABI or in-process loading is used.

Configuration schema 12 extends v0.5 schema 10 with `plugins.directory`, per-plugin `granted_permissions`, and the optional `launcher` command. Loading merges defaults, migrates old keys, and validates before use. Saving writes a temporary file, syncs it, preserves ownership/mode, and atomically renames it.

The static management UI remains separate from the Rust service. Built-ins remain Home Assistant, Digital Signage, and Immich. Immich uses originals for browser-native formats and a full-size fallback for HEIC/RAW, retaining the v0.5.2 contain/cover correction.
