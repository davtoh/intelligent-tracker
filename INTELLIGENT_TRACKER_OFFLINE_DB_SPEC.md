# Intelligent Tracker — Offline-First SQLite Cache & Enterprise Cloud Hub Spec

> **Version:** 1.0 (Milestone 10 / Phase E5 Enterprise Readiness)  
> **Target Module:** `intelligent_tracker.database.TrackerDB`  
> **Companion Document:** `documentation/enterprise_hub_integration.rst`  

---

## 1. Executive Summary

When deployed in remote edge environments (checkpoints, retail branches, distribution warehouses, gate barriers), `intelligent_tracker` functions as an **autonomous edge appliance**. Local network outages or WAN disconnections must never interrupt local gate access control, vehicle license plate verification, or facial Re-ID.

To support full offline resilience, the local SQLite database (`TrackerDB`) maintains an **authoritative offline mirror** synchronized with the central Enterprise Cloud Hub (`davtoh/enterprise-website`).

```
+-------------------------------------------------------------+
| Edge Vision Node (intelligent_tracker)                      |
| - Local SQLite (TrackerDB) with Offline Cache               |
|   * tracker_sync_state (ETags, sync timestamps, counts)     |
|   * local_whitelist (Authorized plates, Re-ID embeddings)   |
|   * offline_access_queue (Buffered gate access attempts)    |
+-------------------------------------------------------------+
           |                         ^                    ^
           | (HMAC-SHA256 Webhook)   | (Range Requests)   | (Delta Sync)
           v                         v                    v
+-------------------------------------------------------------+
| Enterprise Cloud Hub (enterprise-website)                   |
| - /api/v1/security/events/ (X-Tracker-Signature Webhook)    |
| - /api/v1/gallery/stream/<id>/ (Zero-Copy Proxy)            |
| - /api/v1/security/whitelist/ (ETag Delta Sync)             |
| - /api/v1/security/access/ (Offline Outbox Ingestion)       |
+-------------------------------------------------------------+
```

---

## 2. SQLite Offline Cache DDL Specification

### 2.1 Table: `tracker_sync_state`

Tracks incremental synchronization state, last HTTP ETag received from the Hub, and active credential counts.

```sql
CREATE TABLE IF NOT EXISTS tracker_sync_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_key TEXT UNIQUE NOT NULL,
    last_etag TEXT DEFAULT '',
    last_sync_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active_whitelist_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'synced',
    metadata_json TEXT DEFAULT '{}'
);
```

| Column | Type | Description |
|---|---|---|
| `sync_key` | `TEXT UNIQUE` | Identification key (e.g. `'default'`, `'whitelist'`, `'rsac'`). |
| `last_etag` | `TEXT` | HTTP ETag received from Cloud Hub to allow `304 Not Modified` delta polling. |
| `last_sync_timestamp` | `TIMESTAMP` | ISO-8601 UTC timestamp of last successful synchronization. |
| `active_whitelist_count` | `INTEGER` | Cached count of valid, non-banned credentials. |
| `status` | `TEXT` | Sync status (`'synced'`, `'pending'`, `'offline'`). |
| `metadata_json` | `TEXT` | Serialized JSON dictionary for optional sync parameters. |

---

### 2.2 Table: `local_whitelist`

Stores authoritative vehicle license plates, biometric Re-ID feature embeddings (512-d float vectors), clearance tiers, and validity windows for offline access decisions.

```sql
CREATE TABLE IF NOT EXISTS local_whitelist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    credential_id TEXT UNIQUE NOT NULL,
    entity_name TEXT NOT NULL,
    clearance_tier TEXT NOT NULL DEFAULT 'VISITOR',
    plate_number TEXT DEFAULT '',
    embedding BLOB,
    valid_from TIMESTAMP,
    valid_until TIMESTAMP,
    is_banned INTEGER DEFAULT 0,
    sync_version INTEGER DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_whitelist_plate ON local_whitelist(plate_number);
CREATE INDEX IF NOT EXISTS idx_whitelist_tier ON local_whitelist(clearance_tier);
```

| Column | Type | Description |
|---|---|---|
| `credential_id` | `TEXT UNIQUE` | Global UUID / identifier issued by Enterprise Cloud Hub. |
| `entity_name` | `TEXT` | Name of authorized employee, VIP, resident, or registered vehicle. |
| `clearance_tier` | `TEXT` | Access tier (`'VIP'`, `'STAFF'`, `'CONTRACTOR'`, `'VISITOR'`, `'RESTRICTED'`, `'BANNED'`). |
| `plate_number` | `TEXT` | Normalized uppercase alphanumeric plate string. |
| `embedding` | `BLOB` | Precomputed 512-d float32 Re-ID feature vector (2048 bytes). |
| `valid_from` | `TIMESTAMP` | Start time of access permission window (optional). |
| `valid_until` | `TIMESTAMP` | Expiration time of access permission window (optional). |
| `is_banned` | `INTEGER` | Immediate revocation flag (`1` = deny entry, `0` = permitted). |
| `sync_version` | `INTEGER` | Incremental version number for conflict resolution. |

---

### 2.3 Table: `offline_access_queue`

Buffers edge access decisions (barrier openings, turnstile taps, recognized detections) executed during WAN offline periods.

```sql
CREATE TABLE IF NOT EXISTS offline_access_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uuid TEXT UNIQUE NOT NULL,
    credential_id TEXT,
    camera_id TEXT NOT NULL,
    direction TEXT DEFAULT 'in',
    access_granted INTEGER NOT NULL,
    decision_reason TEXT DEFAULT '',
    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    snapshot_path TEXT DEFAULT '',
    synced INTEGER DEFAULT 0,
    synced_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_offline_access_synced ON offline_access_queue(synced);
```

| Column | Type | Description |
|---|---|---|
| `event_uuid` | `TEXT UNIQUE` | Idempotent UUID for the access event. |
| `credential_id` | `TEXT` | Matching credential ID from `local_whitelist`, or `NULL` if unidentified. |
| `camera_id` | `TEXT` | Channel identifier (e.g. `'cam_01'`). |
| `direction` | `TEXT` | Gate movement vector (`'in'` or `'out'`). |
| `access_granted` | `INTEGER` | Access decision (`1` = granted, `0` = denied). |
| `decision_reason` | `TEXT` | Rationale (`'whitelist_match'`, `'expired_credential'`, `'banned'`, `'unknown'`). |
| `synced` | `INTEGER` | Outbox sync flag (`0` = pending upload to Hub, `1` = synced). |
| `synced_at` | `TIMESTAMP` | Timestamp when Cloud Hub acknowledged receipt. |

---

## 3. Hub Integration & Security Protocols

### 3.1 Edge-to-Hub Security Webhook Signature (`X-Tracker-Signature`)

Outbound security webhooks sent via `WebhookDispatcher` are signed with HMAC-SHA256:

```python
import hmac
import hashlib

def compute_signature(secret: str, body_bytes: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
```

The hex digest is transmitted in HTTP header `X-Tracker-Signature`.

### 3.2 Real-Time Edge Telemetry REST Endpoint

Central Cloud Hub canvas overlays proxy real-time tracking states via:

```http
GET /api/cameras/{camera_id}/telemetry
```

Response format:

```json
{
  "camera_id": "cam_01",
  "status": "online",
  "fps": 29.8,
  "resolution": "1920x1080",
  "active_tracks": [
    {
      "id": 14,
      "bbox": [320, 180, 510, 640],
      "centroid": [415.0, 410.0],
      "ground_pos": [3.5, 8.2],
      "velocity": [0.15, -0.02],
      "label": "person",
      "confidence": 0.92,
      "dwell_time": 14.2,
      "entity_name": "Alice Johnson",
      "category": "vip"
    }
  ],
  "zones": [
    {
      "name": "Entrance Lobby",
      "occupancy": 3,
      "capacity_limit": 10
    }
  ],
  "tripwires": []
}
```

---

## 4. Usage Example

```python
from intelligent_tracker.database import TrackerDB

db = TrackerDB("data/tracker.db")

# 1. Update sync state from Cloud Hub response
db.update_sync_state(sync_key="whitelist", last_etag="W/'abc123etag'", active_whitelist_count=42)

# 2. Upsert authorized vehicle / individual
db.upsert_whitelist_entry(
    credential_id="cred_vip_001",
    entity_name="Alice Johnson",
    clearance_tier="VIP",
    plate_number="XYZ-789",
)

# 3. Queue offline access attempt during WAN disconnection
db.enqueue_offline_access(
    event_uuid="ev_gate_001",
    camera_id="cam_01",
    access_granted=True,
    credential_id="cred_vip_001",
    decision_reason="whitelist_match",
)

# 4. Flush offline queue when connectivity returns
pending = db.get_pending_offline_access()
# ... POST to Cloud Hub /api/v1/security/access/ ...
db.mark_offline_access_synced([p["event_uuid"] for p in pending])
```

