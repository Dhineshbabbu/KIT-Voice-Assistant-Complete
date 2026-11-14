import sqlite3, secrets, time
from pathlib import Path
from app.config import settings

def connect():
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(settings.database_path, timeout=20)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS sessions(
          sid TEXT PRIMARY KEY, college_token TEXT NOT NULL, login_id TEXT NOT NULL,
          role TEXT NOT NULL, user_json TEXT NOT NULL DEFAULT '{}', expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversations(
          id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT NOT NULL,
          role TEXT NOT NULL, content TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pending_actions(
          action_id TEXT PRIMARY KEY, sid TEXT NOT NULL, action_type TEXT NOT NULL,
          payload_json TEXT NOT NULL, expires_at INTEGER NOT NULL
        );
        ''')
        # Upgrade an earlier MVP database without losing its conversation history.
        cols = {r["name"] for r in db.execute("PRAGMA table_info(sessions)")}
        if "user_json" not in cols:
            db.execute("ALTER TABLE sessions ADD COLUMN user_json TEXT NOT NULL DEFAULT '{}'")

def create_session(token, login_id, role, user, hours=8):
    sid = secrets.token_urlsafe(32)
    import json
    with connect() as db:
        db.execute("INSERT INTO sessions(sid,college_token,login_id,role,user_json,expires_at) VALUES(?,?,?,?,?,?)",
                   (sid, token, login_id, role, json.dumps(user), int(time.time()) + hours*3600))
    return sid

def get_session(sid):
    if not sid: return None
    with connect() as db:
        row = db.execute("SELECT * FROM sessions WHERE sid=? AND expires_at>?", (sid, int(time.time()))).fetchone()
    if not row: return None
    result = dict(row)
    import json
    result["user"] = json.loads(result.pop("user_json") or "{}")
    return result

def delete_session(sid):
    if not sid: return
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE sid=?", (sid,))
        db.execute("DELETE FROM pending_actions WHERE sid=?", (sid,))

def add_message(sid, role, content):
    with connect() as db:
        db.execute("INSERT INTO conversations(sid,role,content,created_at) VALUES(?,?,?,?)",
                   (sid, role, content, int(time.time())))

def history(sid, limit=100):
    with connect() as db:
        rows = db.execute("SELECT role,content,created_at FROM conversations WHERE sid=? ORDER BY id DESC LIMIT ?",
                          (sid, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]

def save_pending_action(action_id, sid, action_type, payload, minutes=10):
    import json
    with connect() as db:
        db.execute("INSERT INTO pending_actions VALUES(?,?,?,?,?)",
                   (action_id, sid, action_type, json.dumps(payload), int(time.time()) + minutes*60))

def pop_pending_action(action_id, sid):
    import json
    with connect() as db:
        row = db.execute("SELECT * FROM pending_actions WHERE action_id=? AND sid=? AND expires_at>?",
                         (action_id, sid, int(time.time()))).fetchone()
        if not row: return None
        db.execute("DELETE FROM pending_actions WHERE action_id=?", (action_id,))
    return {"action_type": row["action_type"], "payload": json.loads(row["payload_json"])}
