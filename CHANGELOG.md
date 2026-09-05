# Changelog

## [0.2.0] - 2026-09-05

- Added streaming support via `aprocess_stream`, including safe post-processing behavior when streams are cancelled mid-response.
- Added a non-coder CLI setup flow with `cyrrus init` for generating `slides.json` configs quickly.
- Added temporal memory versioning so updated facts supersede old values instead of overwriting history.
- Added tiered fact extraction: regex by default, optional ONNX (`cyrrus[facts-onnx]`), and optional torch (`cyrrus[facts-torch]`).
- Fixed tray concurrency behavior under load for more reliable multi-session operation.
- Fixed long-conversation token consistency by bounding the "Previously mentioned" compression block; savings now stay stable around 64-80% at 100+ messages instead of decaying to ~26% by message 11.

Thanks to Ali Aldiry for real-world testing that surfaced the token consistency bug this release fixes.

