# Alpine / OpenRC notes — kioskctl 0.3

Alpine remains an experimental target, but V0.3 adds a real graphical-session implementation rather than installing only the agent.

The installer adds `seatd`, keeps tty1 free for administration, and launches Cage/Chromium on VT7 through OpenRC. The `kioskctl` user is added to available `seat`, `video`, `render`, `input`, and `audio` groups.

Audio now falls back through:

```text
PipeWire -> PulseAudio -> ALSA/amixer
```

which is intended to cover minimal Alpine installs where no PipeWire user sink is available.

Install/test with the same commands as the other platforms:

```bash
./install.sh --dry-run
sudo ./install.sh --url "https://example.com"
sudo kioskctl enable-kiosk
sudo kioskctl doctor --json
```

OpenRC logs:

```bash
tail -n 200 /var/log/kioskctl-agent.log
tail -n 200 /var/log/kioskctl-browser.log
```
