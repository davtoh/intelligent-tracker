"""Camera Vendor RTSP URL Presets and Credential Formatter.

Constructs vendor-specific RTSP stream endpoints with URL-encoded credentials
for major camera manufacturers (Hikvision, TP-Link Tapo, EZVIZ, Dahua, Generic).
"""

import urllib.parse
from typing import Any, Dict, List


def _format_auth_prefix(username: str, password: str) -> str:
    """Encodes username and password into a URL authority prefix."""
    user_enc = urllib.parse.quote(username, safe="") if username else ""
    pass_enc = urllib.parse.quote(password, safe="") if password else ""
    if user_enc and pass_enc:
        return f"{user_enc}:{pass_enc}@"
    if user_enc:
        return f"{user_enc}@"
    return ""


def _build_netloc(preset: str, auth_part: str, ip: str, port: int, pass_enc: str) -> str:
    """Builds the network location authority string."""
    port_str = f":{port}" if port != 554 else ""
    if preset in ("ezviz",):
        auth_ez = f"admin:{pass_enc}@" if pass_enc else auth_part
        return f"{auth_ez}{ip}{port_str}"
    return f"{auth_part}{ip}{port_str}"


def _build_vendor_path(preset: str, channel: int, stream: str) -> str:
    """Builds the stream path based on vendor preset."""
    if preset in ("hikvision", "hik"):
        suffix = "01" if stream.lower() == "main" else "02"
        return f"/Streaming/Channels/{channel}{suffix}"
    if preset in ("tapo", "tp-link"):
        path = "stream1" if stream.lower() == "main" else "stream2"
        return f"/{path}"
    if preset in ("ezviz",):
        suffix = "main" if stream.lower() == "main" else "sub"
        return f"/h264/ch{channel}/{suffix}"
    if preset in ("dahua", "imou"):
        subtype = 0 if stream.lower() == "main" else 1
        return f"/cam/realmonitor?channel={channel}&subtype={subtype}"
    return "/live"


def build_preset_rtsp_url(
    preset: str,
    ip: str,
    port: int = 554,
    username: str = "",
    password: str = "",
    channel: int = 1,
    stream: str = "main",
) -> str:
    """
    Constructs vendor-specific RTSP stream URLs with URL-encoded credentials.

    Supported Presets:
    - hikvision: `rtsp://{user}:{pass}@{ip}:{port}/Streaming/Channels/{channel}01` (main) or `02` (sub)
    - tapo:      `rtsp://{user}:{pass}@{ip}:{port}/stream1` (HD) or `/stream2` (SD)
    - ezviz:     `rtsp://admin:{verification_code}@{ip}:{port}/h264/ch{channel}/main`
    - dahua:     `rtsp://{user}:{pass}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype={0|1}`
    - generic:   `rtsp://{user}:{pass}@{ip}:{port}/live`

    Args:
        preset: Vendor preset name.
        ip: Camera IP address or hostname.
        port: RTSP port (default 554).
        username: Username / admin account.
        password: Password or verification code.
        channel: Channel index (default 1).
        stream: 'main' or 'sub'.

    Returns:
        Formatted RTSP URL string.
    """
    preset = (preset or "generic").strip().lower()
    auth_part = _format_auth_prefix(username, password)
    pass_enc = urllib.parse.quote(password, safe="") if password else ""
    netloc = _build_netloc(preset, auth_part, ip, port, pass_enc)
    path = _build_vendor_path(preset, channel, stream)
    return f"rtsp://{netloc}{path}"


CAMERA_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "hikvision",
        "name": "Hikvision NVR / IP Camera",
        "default_port": 554,
        "template": "rtsp://{user}:{pass}@{ip}:554/Streaming/Channels/{channel}01",
        "notes": "Main stream uses {channel}01, sub-stream uses {channel}02",
    },
    {
        "id": "tapo",
        "name": "TP-Link Tapo (C200 / C310 / C500)",
        "default_port": 554,
        "template": "rtsp://{user}:{pass}@{ip}:554/stream1",
        "notes": "stream1 = 1080p/2K HD, stream2 = 360p SD. Create camera account in Tapo App settings.",
    },
    {
        "id": "ezviz",
        "name": "EZVIZ Security Camera",
        "default_port": 554,
        "template": "rtsp://admin:{verification_code}@{ip}:554/h264/ch1/main",
        "notes": "Username is always 'admin', password is the 6-character Verification Code printed on camera sticker.",
    },
    {
        "id": "dahua",
        "name": "Dahua / Imou IP Camera",
        "default_port": 554,
        "template": "rtsp://{user}:{pass}@{ip}:554/cam/realmonitor?channel={channel}&subtype=0",
        "notes": "subtype=0 for main stream, subtype=1 for sub stream.",
    },
    {
        "id": "generic",
        "name": "Generic RTSP Stream / NVR Channel",
        "default_port": 554,
        "template": "rtsp://{user}:{pass}@{ip}:{port}/live",
        "notes": "Standard RTSP endpoint URI.",
    },
]
