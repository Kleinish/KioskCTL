.PHONY: test check build release
test:
	cargo test --all-targets
check:
	cargo fmt --check
	cargo clippy --all-targets -- -D warnings
	sh -n install.sh scripts/rollback-0.6.sh
build:
	cargo build
release:
	cargo build --release
