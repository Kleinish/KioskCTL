# Building kioskctl on WSL

Build on a current Ubuntu or Debian WSL distribution. The project requires Rust 1.88 or newer.

## One-time workstation setup

```bash
sudo apt update
sudo apt install -y build-essential pkg-config musl-tools curl git
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
rustup toolchain install 1.88.0
rustup default 1.88.0
rustup target add x86_64-unknown-linux-gnu x86_64-unknown-linux-musl
```

Confirm the setup:

```bash
rustc --version
cargo --version
musl-gcc --version
```

## Build the two x86_64 Linux binaries

From the repository root:

```bash
cargo build --release --target x86_64-unknown-linux-gnu
CC_x86_64_unknown_linux_musl=musl-gcc cargo build --release --target x86_64-unknown-linux-musl
```

The resulting files are:

| File | Deploy to |
|---|---|
| `target/x86_64-unknown-linux-gnu/release/kioskctl` | Fedora, Debian, Arch Linux |
| `target/x86_64-unknown-linux-musl/release/kioskctl` | Alpine Linux |

The musl target makes the Alpine binary self-contained. Do **not** deploy the glibc (`gnu`) binary to Alpine.

## Prepare a release directory

```bash
mkdir -p dist/gnu dist/musl
cp target/x86_64-unknown-linux-gnu/release/kioskctl dist/gnu/
cp target/x86_64-unknown-linux-musl/release/kioskctl dist/musl/
cp -a install.sh uninstall.sh systemd openrc scripts web examples docs README.md LICENSE CHANGELOG.md dist/
```

The Rust binary is only the management agent. Each kiosk still needs its native packages and session dependencies: Cage, Chromium when using the browser launcher, SeatD, and the appropriate systemd or OpenRC service files. Use `install.sh` from the release directory on the target host.

To install a prebuilt binary without Rust or Cargo on the kiosk, copy the matching file into the release directory and pass its path explicitly:

```bash
# Fedora, Debian, or Arch
sudo KIOSKCTL_BINARY="$PWD/dist/gnu/kioskctl" ./install.sh

# Alpine
sudo KIOSKCTL_BINARY="$PWD/dist/musl/kioskctl" ./install.sh
```

## Optional: build the native application variant

No different Rust binary is needed. Deploy the same target-appropriate `kioskctl` binary, then configure the kiosk to launch your application:

```yaml
launcher:
  command: /opt/my-kiosk-app/my-kiosk-app
  args: ["--fullscreen"]
  working_directory: /opt/my-kiosk-app
```

Leave `launcher.command` empty to launch Chromium.
