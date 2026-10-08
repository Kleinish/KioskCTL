# kioskctl 0.5.2

## Immich original-source fitting fix

0.5.2 corrects two problems found while validating the Immich screensaver:

- **Contain and Cover now use explicit pixel geometry.** The slideshow calculates the scale from the asset's natural width/height and the current Chromium viewport instead of depending only on CSS `object-fit`.
- **Browser-native photos use the original Immich asset.** JPEG, PNG, WebP, AVIF, GIF, APNG and BMP are fetched through `/api/assets/{id}/original`, so a generated Immich derivative cannot pre-crop the source before kioskctl applies Contain. HEIC/HEIF/RAW and other browser-incompatible formats use `/thumbnail?size=fullsize` as a compatibility fallback.
- **The Immich loading label no longer overlays photos.** The explicit `[hidden]` rule prevents the centered loading message from remaining visible like a watermark.
- **Preview refreshes after setting changes.** Clicking Preview while a screensaver preview is already active reloads it so fit/background changes take effect immediately.

The API key should include **asset view** and **asset download** permissions because browser-native assets now intentionally use the original-download endpoint.

## Upgrade

```bash
unzip -o kioskctl-v0.5.2.zip
cd kioskctl-v0.5.2
sudo ./install.sh
sudo kioskctl restart-kiosk
```

Use an in-place upgrade to preserve MQTT/Home Assistant, plugin configuration, browser state and local signage assets.
