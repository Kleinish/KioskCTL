# kioskctl 0.5.1

## Immich aspect-ratio hotfix

0.5.1 fixes Immich screensaver images appearing cropped even when **Image fit → Contain** is selected.

The kiosk page's `object-fit` behavior was already correct, but 0.5.0 proxied Immich's `size=preview` derivative. If the derivative itself has already lost part of the source image, CSS cannot recover those missing pixels. This is especially visible with affected HEIC/HEIF previews.

0.5.1 changes the Immich slideshow source to the API's `size=fullsize` representation and leaves the final framing to Chromium:

- **Contain** displays the whole image and letterboxes/pillarboxes as needed.
- **Cover / fill screen** deliberately fills the panel and crops only the excess required by the screen's aspect ratio.
- Images are centered with explicit viewport sizing (`100vw × 100vh`).
- The Web UI reports `full-size source` in Immich status.

Immich may redirect a full-size request to the original asset for browser-compatible image formats. On Immich configurations that use restricted API-key permissions, the key therefore needs both asset-view and asset-download access. kioskctl now reports a clear error if Immich rejects that request. **Test connection** also fetches one real full-size sample so a restricted API key is caught before the screensaver starts.

## Upgrade

Use an in-place upgrade so your existing kiosk, MQTT/Home Assistant and Immich settings are retained:

```bash
unzip -o kioskctl-v0.5.1.zip
cd kioskctl-v0.5.1
sudo ./install.sh
sudo kioskctl restart-kiosk
```

No config migration or re-entry of the stored Immich API key is required.
