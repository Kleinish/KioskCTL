# Contributing

Use Rust 1.88+. Before a pull request run `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, and `cargo test --all-targets`. Preserve API/config compatibility unless the change includes a migration and release note. Plugins use `docs/PLUGINS.md`.
