# Rule: Security & Engineering Standards

## Purpose
Enforce industry-standard best practices, IoT/CCTV edge security, video privacy compliance, resource safety, and modern Python conventions across all project modernizations and migrations.

## Guidelines
1. **Security & Privacy First:**
   - **Secrets Management**: Never commit camera RTSP credentials (`rtsp://user:password@ip`), MQTT broker passwords, Webhook URLs, or Telegram bot tokens in source control. Always utilize `.env` files and environment variables. Provide a `.env.example` template.
   - **Video Privacy & GDPR Compliance**: Provide configuration toggles for privacy masking, face blurring, and metadata-only telemetry (e.g. sending bounding box coordinates or person counts rather than storing/transmitting raw video footage).
   - **Safe Network Sockets**: Validate and sanitize external webhook endpoints, RTSP URLs, and MQTT payloads to prevent SSRF or command injection.
2. **CCTV Pipeline Stability & Resource Management:**
   - **Frame Buffer Safety & Memory Leaks**: Prevent frame accumulation in `cv2.VideoCapture` queues. Always use context managers or explicit cleanup (`cap.release()`, `cv2.destroyAllWindows()`).
   - **Thread Safety**: Isolate video acquisition, AI inference, and UI rendering into cleanly synchronized threads/queues to avoid freezing the pipeline.
   - **Hardware & Device Fallbacks**: Ensure scripts and tests never crash if a physical webcam, Raspberry Pi GPIO, or Edge TPU accelerator is missing. Always provide synthetic frames or mock fallbacks.
3. **Cross-Platform Compatibility:**
   - Code must run seamlessly across Windows (PowerShell/CMD), Linux (Ubuntu, Debian, Raspberry Pi OS), and macOS (Apple Silicon & Intel).
   - Use `pathlib.Path` or `os.path` for path manipulation; never hardcode POSIX (`/`) or Windows (`\`) slashes.
   - Replace Unix-only modules (such as `import resource`) with cross-platform alternatives (`psutil`).
4. **Idiomatic Modern Python:**
   - Target modern Python (3.10 - 3.12+).
   - Progressively phase out obsolete Python 2/3 shims (`from __future__ import ...`, `from builtins import object`, `six`, `future`) in favor of native Python 3 constructs and type annotations.
   - Use standard `logging` rather than scattered `print()` statements.
