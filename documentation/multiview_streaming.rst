.. _multiview_streaming:

Multi-View WebSocket Streaming & Grid Scalability
=================================================

The ``/ws/multiview`` multiplexer delivers downscaled, FPS-capped JPEG thumbnails for **2x2**, **3x3**, and **4x4** camera matrices over a single binary WebSocket connection per browser tab. Combined with grid pagination, this allows dashboards with arbitrary camera counts (e.g., 100 channels) to stay well within the browser's 6-socket HTTP/1.1 connection pool without starving Video Studio or REST telemetry requests.

.. note::

   **Viewing ≠ Analytics:** Multiview subscriptions wake camera capture via ``annotated=False`` subscriber leases so thumbnail frames flow immediately, but never drive AI inference. Inference cadence remains governed strictly by ``ProcessingModeService`` and each camera's ``armed`` policy.

Browser Socket Budget (Per SPA Tab)
-----------------------------------

.. list-table::
   :header-rows: 1
   :widths: 28 16 16 40

   * - Active View
     - WebSocket
     - MJPEG
     - Headroom for ``fetch()`` / MP4 Range
   * - ``1x1`` Focused Monitor
     - 0--1 (closes after 30 s idle)
     - 1 (``/stream/{id}?annotated=false``)
     - >= 4 sockets free
   * - ``2x2`` / ``3x3`` / ``4x4`` (WS mode)
     - 1 (``/ws/multiview``)
     - 0
     - >= 5 sockets free
   * - Grid (MJPEG fallback mode)
     - 0 (background backoff retry)
     - <= 4 (forced ``2x2`` pages)
     - >= 2 sockets free
   * - Video Studio / Other Tabs
     - 0--1 (``unsubscribe_all``, 30 s idle close)
     - 0
     - >= 5 sockets free

``/ws/multiview`` Protocol v1
-----------------------------

Binary Server → Client Frame Layout
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Each thumbnail frame is sent as a single binary WebSocket message containing a 16-byte big-endian header, the UTF-8 ``camera_id``, and the raw JPEG payload:

.. list-table::
   :header-rows: 1
   :widths: 12 12 20 56

   * - Offset
     - Size
     - Field
     - Description
   * - ``0``
     - 1 byte
     - ``version``
     - Protocol version (``0x01``).
   * - ``1``
     - 1 byte
     - ``kind``
     - Payload kind (``0x01`` = JPEG thumbnail; other values reserved).
   * - ``2``
     - 2 bytes
     - ``cam_id_len``
     - Unsigned 16-bit big-endian length of UTF-8 ``camera_id`` (1--65535).
   * - ``4``
     - 4 bytes
     - ``seq``
     - Monotonic per-camera ``uint32`` frame sequence (wraps modulo 2\ :sup:`32`).
   * - ``8``
     - 8 bytes
     - ``capture_ts_ms``
     - Capture epoch timestamp in milliseconds (``uint64``).
   * - ``16``
     - ``cam_id_len``
     - ``camera_id``
     - UTF-8 encoded camera identifier.
   * - ``16 + len``
     - remaining
     - ``payload``
     - Encoded JPEG bytes from the shared ``ThumbnailCache`` tier.

JSON Control Messages
^^^^^^^^^^^^^^^^^^^^^

* **Client → Server:**

  * ``{"v": 1, "action": "subscribe", "cameras": ["cam_01", "cam_02"], "layout": "3x3", "profile": "thumb", "max_fps": 10, "max_width": 480}`` — **Full replacement** of the session's active camera set (never additive). ``profile: "full"`` is reserved in v1 and returns ``error`` code ``profile_not_enabled``.
  * ``{"v": 1, "action": "unsubscribe_all"}`` — Immediately drops all camera leases; client closes the socket after 30 s idle.
  * ``{"v": 1, "action": "pause"}`` / ``{"v": 1, "action": "resume"}`` — Releases or restores active camera leases on ``document.hidden`` transitions.
  * ``{"v": 1, "action": "ping"}`` — Keepalive check returning ``pong``.

* **Server → Client:**

  * ``hello`` — Sent on connect with ``protocol``, server ``limits``, and per-layout ``layouts`` caps.
  * ``subscribed`` — Reports ``accepted`` list, ``rejected`` map (e.g., ``unknown_camera``, ``disabled``), and clamped ``fps``/``width``.
  * ``source_status`` — Edge-triggered status change (``online``, ``hibernating``, ``reconnecting``, ``error``, ``offline``, ``disabled``) with ``reason``.
  * ``pong`` / ``error`` — Keepalive reply or structured validation error (``code``, ``message``).

* **WebSocket Close Codes:** ``1000`` (clean/idle close), ``1001`` (server shutdown/reload), ``1008`` (Origin or HMAC token rejected), ``1013`` (concurrent session cap reached — retryable).

Configuration & Security
------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 28 42

   * - Environment Variable
     - Default
     - Purpose
   * - ``MULTIVIEW_LAYOUT_CAPS``
     - ``2x2:15:640,3x3:10:480,4x4:6:320``
     - Per-layout ``fps:max_width`` ceilings.
   * - ``MULTIVIEW_MAX_SUBSCRIPTIONS``
     - ``16``
     - Maximum cameras per ``subscribe`` request (``4x4``).
   * - ``MULTIVIEW_MAX_SESSIONS``
     - ``16``
     - Maximum concurrent ``/ws/multiview`` sessions per node.
   * - ``MULTIVIEW_SEND_TIMEOUT_S``
     - ``0.5``
     - Per-frame send deadline; slow clients skip stale frames.
   * - ``MULTIVIEW_THUMB_QUALITY``
     - ``70``
     - JPEG quality (10--100) for shared thumbnail encoding.
   * - ``ALLOWED_ORIGINS``
     - ``""`` (same-origin only)
     - Comma-separated extra CORS & WebSocket ``Origin`` allowlist.
   * - ``MULTIVIEW_TOKEN_SECRET``
     - ``""`` (disabled)
     - Enables HMAC-SHA256 ``?token=`` verification (``exp`` <= 300 s) on ``/ws/*``.
   * - ``FORWARDED_ALLOW_IPS``
     - ``""`` (uvicorn default)
     - Trusted reverse-proxy IPs passed to ``uvicorn.run(..., proxy_headers=True)``.

When ``MULTIVIEW_TOKEN_SECRET`` is configured, generate short-lived signed tokens (TTL <= 300 s) on the Hub before opening ``/ws/multiview?token=...`` or ``/ws/{camera_id}?token=...``:

.. code-block:: python

   from dashboard.services.security_config import sign_token

   token = sign_token(subject="hub-operator-1", ttl_s=120, secret=shared_secret)

Transport Fallback, Auto-Restore & Armed Cameras
------------------------------------------------

* **3-Failure Fallback & Auto-Restore:** If ``/ws/multiview`` experiences 3 consecutive connection failures (``1006``, ``1008``, or sustained ``1013``), ``MultiviewWsClient`` switches ``CameraGrid`` into degraded mode: the grid is clamped to ``2x2`` pages (<= 4 MJPEG sockets) and displays a ``Degraded transport`` badge while retrying the WebSocket in the background with exponential backoff (1 s up to 60 s). Once the handshake succeeds, ``CameraGrid`` automatically restores the full ``3x3`` / ``4x4`` canvas view.
* **Armed Cameras vs. Paused Override:** Cameras configured with ``armed: true`` stay awake for capture and analytics in ``focus_only`` and ``capture_only`` modes even when unsubscribed. Switching the system to ``paused`` overrides ``armed`` (unless actively recording) and displays the count of paused armed cameras in the live overlay.

Reverse-Proxy Recipes (TLS, HTTP/2 & WebSocket Upgrade)
-------------------------------------------------------

Browser HTTP/2 requires TLS (ALPN ``h2``). Terminate TLS at Caddy or Nginx in front of Uvicorn and set ``FORWARDED_ALLOW_IPS`` to the proxy host IP so ``X-Forwarded-For`` and ``X-Forwarded-Proto`` are preserved.

Caddy Example (``Caddyfile``)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: text

   edge-cam-01.example.com {
       # Caddy enables HTTP/2 + HTTP/3 over TLS and forwards WebSocket upgrades automatically.
       reverse_proxy 127.0.0.1:8000 {
           flush_interval -1
       }
   }

Nginx Example (``/etc/nginx/conf.d/intelligent_tracker.conf``)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: nginx

   map $http_upgrade $connection_upgrade {
       default upgrade;
       ''      close;
   }

   server {
       listen 443 ssl;
       http2 on;
       server_name edge-cam-01.example.com;

       ssl_certificate     /etc/ssl/certs/edge.crt;
       ssl_certificate_key /etc/ssl/private/edge.key;

       # WebSocket multiplexer & per-camera telemetry
       location /ws/ {
           proxy_pass http://127.0.0.1:8000;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection $connection_upgrade;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_read_timeout 86400s;
       }

       # Unbuffered MJPEG & HTTP Range video streaming
       location /stream/ {
           proxy_pass http://127.0.0.1:8000;
           proxy_buffering off;
           proxy_cache off;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }

Verification & Scenario Matrix
------------------------------

Pre-run checks:

.. code-block:: bash

   MPLBACKEND=Agg python -m unittest tests.test_multiview_protocol tests.test_thumbnail_cache tests.test_multiview_session tests.test_multiview_router tests.test_frame_surface tests.test_multiview_client
   python -m sphinx -W --keep-going documentation/ documentation/_build/html/

.. list-table::
   :header-rows: 1
   :widths: 24 22 24 30

   * - Scenario
     - Inputs / Env
     - Expected Result
     - Command
   * - Default same-origin WS
     - ``ALLOWED_ORIGINS=""``
     - Cross-origin rejected with ``1008``
     - ``MPLBACKEND=Agg python -m unittest tests.test_security_config``
   * - Cross-origin Hub + HMAC
     - ``ALLOWED_ORIGINS="https://hub.local"`` ``MULTIVIEW_TOKEN_SECRET="..."``
     - Valid signed ``?token=`` accepted; expired rejected ``1008``
     - ``MPLBACKEND=Agg python -m unittest tests.test_multiview_router``
   * - Forced fallback test
     - ``MULTIVIEW_MAX_SESSIONS=0``
     - ``1013`` close -> 3x triggers ``2x2`` MJPEG fallback + badge
     - ``MULTIVIEW_MAX_SESSIONS=0 python scripts/run_dashboard.py --local --no-reload``
   * - Behind local Nginx/Caddy
     - ``FORWARDED_ALLOW_IPS="127.0.0.1"``
     - Proxy headers trusted; WebSocket upgrades pass
     - ``FORWARDED_ALLOW_IPS="127.0.0.1" python scripts/run_dashboard.py --local --no-reload``
