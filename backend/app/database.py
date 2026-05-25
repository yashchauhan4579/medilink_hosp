import sqlite3
import json
import threading
from contextlib import contextmanager
from datetime import datetime
from app.config import DATABASE_PATH

_local = threading.local()


def get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


@contextmanager
def get_db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cameras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                rtsp_url TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS rois (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
                module TEXT NOT NULL CHECK (module IN ('reception', 'crowd')),
                polygon TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(camera_id, module)
            );

            CREATE TABLE IF NOT EXISTS module_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
                module TEXT NOT NULL CHECK (module IN ('reception', 'crowd')),
                enabled INTEGER NOT NULL DEFAULT 0,
                absence_timeout_sec INTEGER DEFAULT 30,
                crowd_threshold INTEGER DEFAULT 5,
                confidence_threshold REAL DEFAULT 0.45,
                alert_cooldown_sec INTEGER DEFAULT 60,
                UNIQUE(camera_id, module)
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
                module TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                head_count INTEGER,
                snapshot_path TEXT,
                whatsapp_status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                acknowledged_at TEXT,
                resolved_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_alerts_camera ON alerts(camera_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)

        # Migration: add clip_path column if missing
        try:
            conn.execute("ALTER TABLE alerts ADD COLUMN clip_path TEXT")
        except Exception:
            pass  # column already exists

        defaults = {
            "inference_fps": "6",
            "jpeg_quality": "70",
            "whatsapp_instance_id": "",
            "whatsapp_api_token": "",
            "whatsapp_recipient_phone": "",
            "whatsapp_enabled": "false",
        }
        for key, value in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )


# --- Helper functions ---

def get_all_cameras():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM cameras ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def get_camera(camera_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
        return dict(row) if row else None


def create_camera(name: str, rtsp_url: str):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO cameras (name, rtsp_url) VALUES (?, ?)",
            (name, rtsp_url),
        )
        camera_id = cur.lastrowid
        # Create default module configs
        for module in ("reception", "crowd"):
            conf_thresh = 0.40 if module == "reception" else 0.50
            conn.execute(
                "INSERT INTO module_config (camera_id, module, confidence_threshold) VALUES (?, ?, ?)",
                (camera_id, module, conf_thresh),
            )
        return get_camera(camera_id)


def update_camera(camera_id: int, name: str = None, rtsp_url: str = None, enabled: bool = None):
    with get_db() as conn:
        updates = []
        params = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if rtsp_url is not None:
            updates.append("rtsp_url = ?")
            params.append(rtsp_url)
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(int(enabled))
        if updates:
            updates.append("updated_at = datetime('now')")
            params.append(camera_id)
            conn.execute(
                f"UPDATE cameras SET {', '.join(updates)} WHERE id = ?",
                params,
            )
        return get_camera(camera_id)


def delete_camera(camera_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))


def get_roi(camera_id: int, module: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM rois WHERE camera_id = ? AND module = ?",
            (camera_id, module),
        ).fetchone()
        if row:
            r = dict(row)
            r["polygon"] = json.loads(r["polygon"])
            return r
        return None


def save_roi(camera_id: int, module: str, polygon: list):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO rois (camera_id, module, polygon) VALUES (?, ?, ?)
               ON CONFLICT(camera_id, module) DO UPDATE SET polygon = excluded.polygon,
               created_at = datetime('now')""",
            (camera_id, module, json.dumps(polygon)),
        )
    return get_roi(camera_id, module)


def get_module_config(camera_id: int, module: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM module_config WHERE camera_id = ? AND module = ?",
            (camera_id, module),
        ).fetchone()
        return dict(row) if row else None


def update_module_config(camera_id: int, module: str, **kwargs):
    with get_db() as conn:
        allowed = {"enabled", "absence_timeout_sec", "crowd_threshold",
                    "confidence_threshold", "alert_cooldown_sec"}
        updates = []
        params = []
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                updates.append(f"{k} = ?")
                params.append(v)
        if updates:
            params.extend([camera_id, module])
            conn.execute(
                f"UPDATE module_config SET {', '.join(updates)} WHERE camera_id = ? AND module = ?",
                params,
            )
    return get_module_config(camera_id, module)


def create_alert(camera_id: int, module: str, message: str, head_count: int = None,
                 snapshot_path: str = None, clip_path: str = None):
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO alerts (camera_id, module, message, head_count, snapshot_path, clip_path)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (camera_id, module, message, head_count, snapshot_path, clip_path),
        )
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def get_alerts(camera_id: int = None, module: str = None, status: str = None,
               limit: int = 50, offset: int = 0):
    with get_db() as conn:
        query = "SELECT a.*, c.name as camera_name FROM alerts a LEFT JOIN cameras c ON a.camera_id = c.id"
        conditions = []
        params = []
        if camera_id:
            conditions.append("a.camera_id = ?")
            params.append(camera_id)
        if module:
            conditions.append("a.module = ?")
            params.append(module)
        if status:
            conditions.append("a.status = ?")
            params.append(status)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY a.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def acknowledge_alert(alert_id: int):
    with get_db() as conn:
        conn.execute(
            "UPDATE alerts SET status = 'acknowledged', acknowledged_at = datetime('now') WHERE id = ?",
            (alert_id,),
        )


def resolve_alert(alert_id: int):
    with get_db() as conn:
        conn.execute(
            "UPDATE alerts SET status = 'resolved', resolved_at = datetime('now') WHERE id = ?",
            (alert_id,),
        )


def get_active_alert_count():
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as count FROM alerts WHERE status = 'active'"
        ).fetchone()
        return row["count"]


def update_alert_whatsapp_status(alert_id: int, status: str):
    with get_db() as conn:
        conn.execute(
            "UPDATE alerts SET whatsapp_status = ? WHERE id = ?",
            (status, alert_id),
        )


def get_setting(key: str):
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def get_all_settings():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}


def update_settings(settings: dict):
    with get_db() as conn:
        for key, value in settings.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
