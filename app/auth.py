import os
import sqlite3
import jwt
import bcrypt
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path("data/admin_users.db")
SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "medbot-admin-secret-key-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


def init_admin_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            phone TEXT UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()


def _get_con():
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(user_id: int, identifier: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": str(user_id), "identifier": identifier, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def register_user(name: str, email: str | None, phone: str | None, password: str) -> dict:
    if not email and not phone:
        raise ValueError("Email or phone number is required")
    if not name.strip():
        raise ValueError("Name is required")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")

    password_hash = hash_password(password)
    con = _get_con()
    try:
        con.execute(
            "INSERT INTO admin_users (name, email, phone, password_hash, created_at) VALUES (?,?,?,?,?)",
            (name.strip(), email or None, phone or None, password_hash, datetime.now().isoformat()),
        )
        con.commit()
        user_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        identifier = email or phone
        return {"id": user_id, "name": name.strip(), "token": create_token(user_id, identifier)}
    except sqlite3.IntegrityError as e:
        if "email" in str(e):
            raise ValueError("An account with this email already exists")
        if "phone" in str(e):
            raise ValueError("An account with this phone number already exists")
        raise ValueError("Account already exists")
    finally:
        con.close()


def login_user(identifier: str, password: str) -> dict:
    """Login with email or phone number."""
    con = _get_con()
    user = con.execute(
        "SELECT * FROM admin_users WHERE email=? OR phone=?", (identifier, identifier)
    ).fetchone()
    con.close()

    if not user:
        raise ValueError("No account found with this email or phone number")
    if not verify_password(password, user["password_hash"]):
        raise ValueError("Incorrect password")

    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "phone": user["phone"],
        "token": create_token(user["id"], identifier),
    }


def get_user_by_id(user_id: int) -> dict | None:
    con = _get_con()
    user = con.execute("SELECT id, name, email, phone, created_at FROM admin_users WHERE id=?", (user_id,)).fetchone()
    con.close()
    return dict(user) if user else None


def list_users() -> list[dict]:
    con = _get_con()
    rows = con.execute("SELECT id, name, email, phone, created_at FROM admin_users ORDER BY created_at DESC").fetchall()
    con.close()
    return [dict(r) for r in rows]


def count_admins() -> int:
    con = _get_con()
    row = con.execute("SELECT COUNT(*) AS c FROM admin_users").fetchone()
    con.close()
    return row["c"] if row else 0


def delete_user(user_id: int):
    con = _get_con()
    con.execute("DELETE FROM admin_users WHERE id=?", (user_id,))
    con.commit()
    con.close()
