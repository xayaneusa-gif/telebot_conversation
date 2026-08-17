import json
import random
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


DB_PATH = Path(__file__).with_name("database.db")
STATE_PATH = Path(__file__).with_name("runtime_state.json")
_LOCK = threading.RLock()
_RUNTIME_STATE = {
    "vip_mode": True,
    "traffic_mode": True,
    "abuse_protection": False,
    "not_in_chat_warning": True,
    "uids": [],
    "users": {},
    "payments": [],
}


def _load_runtime_state() -> None:
    global _RUNTIME_STATE
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = None
        if isinstance(data, dict):
            _RUNTIME_STATE["vip_mode"] = bool(data.get("vip_mode", _RUNTIME_STATE["vip_mode"]))
            _RUNTIME_STATE["traffic_mode"] = bool(
                data.get("traffic_mode", data.get("emergency_mode", _RUNTIME_STATE["traffic_mode"]))
            )
            _RUNTIME_STATE["abuse_protection"] = bool(data.get("abuse_protection", _RUNTIME_STATE["abuse_protection"]))
            _RUNTIME_STATE["not_in_chat_warning"] = bool(data.get("not_in_chat_warning", _RUNTIME_STATE["not_in_chat_warning"]))
            raw_uids = data.get("uids", [])
            if isinstance(raw_uids, list):
                uid_set = set()
                for value in raw_uids:
                    try:
                        uid_set.add(int(value))
                    except (TypeError, ValueError):
                        continue
                _RUNTIME_STATE["uids"] = sorted(uid_set)
            raw_users = data.get("users", {})
            if isinstance(raw_users, dict):
                _RUNTIME_STATE["users"] = raw_users
            raw_payments = data.get("payments", [])
            if isinstance(raw_payments, list):
                _RUNTIME_STATE["payments"] = raw_payments[-100:]


def _save_runtime_state() -> None:
    uid_list = sorted({int(value) for value in _RUNTIME_STATE["uids"]})
    payload = {
        "vip_mode": bool(_RUNTIME_STATE["vip_mode"]),
        "traffic_mode": bool(_RUNTIME_STATE["traffic_mode"]),
        "abuse_protection": bool(_RUNTIME_STATE["abuse_protection"]),
        "not_in_chat_warning": bool(_RUNTIME_STATE["not_in_chat_warning"]),
        "uids": uid_list,
        "users": _RUNTIME_STATE["users"],
        "payments": _RUNTIME_STATE["payments"][-100:],
    }
    STATE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


_load_runtime_state()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _LOCK, get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'idle',
                partner_id INTEGER,
                is_emergency INTEGER NOT NULL DEFAULT 0,
                joined_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY,
                age INTEGER,
                gender TEXT NOT NULL DEFAULT 'unspecified',
                preferred_gender TEXT NOT NULL DEFAULT 'any',
                partner_age_min INTEGER,
                partner_age_max INTEGER,
                verified_only INTEGER NOT NULL DEFAULT 0,
                reality_score INTEGER NOT NULL DEFAULT 0,
                verified INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS queue (
                user_id INTEGER PRIMARY KEY,
                joined_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                recipient_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS media_permissions (
                low_user_id INTEGER NOT NULL,
                high_user_id INTEGER NOT NULL,
                allowed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (low_user_id, high_user_id)
            );

            CREATE TABLE IF NOT EXISTS pending_media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                recipient_id INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                file_id TEXT NOT NULL,
                caption TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS feedback_prompts (
                rater_id INTEGER PRIMARY KEY,
                target_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bot_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        existing_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(profiles)").fetchall()
        }
        for column_name, column_type in [
            ("verified_only", "INTEGER NOT NULL DEFAULT 0"),
            ("reality_score", "INTEGER NOT NULL DEFAULT 0"),
            ("verified", "INTEGER NOT NULL DEFAULT 0"),
            ("vip_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("referral_count", "INTEGER NOT NULL DEFAULT 0"),
            ("referred_by", "INTEGER"),
            ("vip_started_at", "TEXT"),
            ("vip_expires_at", "TEXT"),
            ("vip_source", "TEXT"),
            ("last_payment_charge_id", "TEXT"),
        ]:
            if column_name not in existing_columns:
                conn.execute(f"ALTER TABLE profiles ADD COLUMN {column_name} {column_type}")

        user_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "is_emergency" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN is_emergency INTEGER NOT NULL DEFAULT 0")

        if STATE_PATH.exists():
            conn.execute(
                """
                INSERT INTO bot_settings (setting_key, setting_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value = excluded.setting_value,
                    updated_at = excluded.updated_at
                """,
                ("vip_mode", "1" if _RUNTIME_STATE["vip_mode"] else "0", _now()),
            )
            conn.execute(
                """
                INSERT INTO bot_settings (setting_key, setting_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value = excluded.setting_value,
                    updated_at = excluded.updated_at
                """,
                ("traffic_mode", "1" if _RUNTIME_STATE["traffic_mode"] else "0", _now()),
            )
    with _LOCK, get_connection() as conn:
        existing_users = conn.execute("SELECT user_id, name FROM users").fetchall()
    for row in existing_users:
        if int(row["user_id"]) not in _RUNTIME_STATE["uids"]:
            _RUNTIME_STATE["uids"].append(int(row["user_id"]))
        _sync_runtime_user(int(row["user_id"]), row["name"])
    _save_runtime_state()


def ensure_user(user_id: int, name: str) -> None:
    with _LOCK, get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, name, status, partner_id, is_emergency, joined_at, updated_at)
            VALUES (?, ?, 'idle', NULL, 0, NULL, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name = excluded.name,
                updated_at = excluded.updated_at
            """,
            (user_id, name, _now()),
        )
        conn.execute(
            """
            INSERT INTO profiles (
                user_id,
                age,
                gender,
                preferred_gender,
                partner_age_min,
                partner_age_max,
                verified_only,
                reality_score,
                verified,
                vip_enabled,
                referral_count,
                referred_by,
                updated_at
            )
            VALUES (?, NULL, 'unspecified', 'any', NULL, NULL, 0, 0, 0, 0, 0, NULL, ?)
            ON CONFLICT(user_id) DO NOTHING
            """,
            (user_id, _now()),
        )
    if user_id not in _RUNTIME_STATE["uids"]:
        _RUNTIME_STATE["uids"].append(user_id)
    _sync_runtime_user(user_id, name)


def _sync_runtime_user(user_id: int, name: str | None = None) -> None:
    profile = get_profile(user_id)
    record = _RUNTIME_STATE["users"].setdefault(str(user_id), {})
    record.update({
        "uid": int(user_id),
        "name": name or record.get("name") or f"User {user_id}",
        "updated_at": _now(),
    })
    if profile is not None:
        record.update({
            "age": profile["age"],
            "gender": profile["gender"],
            "preferred_gender": profile["preferred_gender"],
            "partner_age_min": profile["partner_age_min"],
            "partner_age_max": profile["partner_age_max"],
            "vip_enabled": bool(profile["vip_enabled"]),
            "vip_started_at": profile["vip_started_at"],
            "vip_expires_at": profile["vip_expires_at"],
            "vip_source": profile["vip_source"],
            "last_payment_charge_id": profile["last_payment_charge_id"],
        })
    _save_runtime_state()


def get_profile(user_id: int):
    with _LOCK, get_connection() as conn:
        return conn.execute(
            "SELECT * FROM profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()


def update_profile(
    user_id: int,
    *,
    age=None,
    gender=None,
    preferred_gender=None,
    partner_age_min=None,
    partner_age_max=None,
    verified_only=None,
    vip_enabled=None,
    referral_count=None,
    referred_by=None,
) -> None:
    with _LOCK, get_connection() as conn:
        existing = conn.execute(
            "SELECT user_id FROM profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO profiles (
                    user_id,
                    age,
                    gender,
                    preferred_gender,
                    partner_age_min,
                    partner_age_max,
                    verified_only,
                    reality_score,
                    verified,
                    vip_enabled,
                    referral_count,
                referred_by,
                vip_started_at,
                vip_expires_at,
                vip_source,
                last_payment_charge_id,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    age,
                    gender or "unspecified",
                    preferred_gender or "any",
                    partner_age_min,
                    partner_age_max,
                    1 if verified_only else 0,
                    0,
                    0,
                    1 if vip_enabled else 0,
                    0 if referral_count is None else referral_count,
                    referred_by,
                    None,
                    None,
                    None,
                    None,
                    _now(),
                ),
            )
            return

        current = conn.execute(
            "SELECT * FROM profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        conn.execute(
            """
            UPDATE profiles
            SET age = ?, gender = ?, preferred_gender = ?, partner_age_min = ?, partner_age_max = ?, verified_only = ?, vip_enabled = ?, referral_count = ?, referred_by = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (
                current["age"] if age is None else age,
                current["gender"] if gender is None else gender,
                current["preferred_gender"] if preferred_gender is None else preferred_gender,
                current["partner_age_min"] if partner_age_min is None else partner_age_min,
                current["partner_age_max"] if partner_age_max is None else partner_age_max,
                current["verified_only"] if verified_only is None else int(bool(verified_only)),
                current["vip_enabled"] if vip_enabled is None else int(bool(vip_enabled)),
                current["referral_count"] if referral_count is None else int(referral_count),
                current["referred_by"] if referred_by is None else referred_by,
                _now(),
                user_id,
            ),
        )


def get_bot_setting(setting_key: str, default: str = "0") -> str:
    with _LOCK, get_connection() as conn:
        row = conn.execute(
            "SELECT setting_value FROM bot_settings WHERE setting_key = ?",
            (setting_key,),
        ).fetchone()
        return str(row["setting_value"]) if row else default


def set_bot_setting(setting_key: str, setting_value: str) -> None:
    with _LOCK, get_connection() as conn:
        conn.execute(
            """
            INSERT INTO bot_settings (setting_key, setting_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET
                setting_value = excluded.setting_value,
                updated_at = excluded.updated_at
            """,
            (setting_key, setting_value, _now()),
        )


def get_vip_mode_enabled() -> bool:
    _load_runtime_state()
    return bool(_RUNTIME_STATE["vip_mode"])


def set_vip_mode_enabled(enabled: bool) -> None:
    _RUNTIME_STATE["vip_mode"] = bool(enabled)
    _save_runtime_state()


def get_traffic_mode_enabled() -> bool:
    _load_runtime_state()
    return bool(_RUNTIME_STATE["traffic_mode"])


def set_traffic_mode_enabled(enabled: bool) -> None:
    _RUNTIME_STATE["traffic_mode"] = bool(enabled)
    _save_runtime_state()


def get_emergency_mode_enabled() -> bool:
    return get_traffic_mode_enabled()


def set_emergency_mode_enabled(enabled: bool) -> None:
    set_traffic_mode_enabled(enabled)


def get_abuse_protection_enabled() -> bool:
    _load_runtime_state()
    return bool(_RUNTIME_STATE["abuse_protection"])


def set_abuse_protection_enabled(enabled: bool) -> None:
    _RUNTIME_STATE["abuse_protection"] = bool(enabled)
    _save_runtime_state()


def get_not_in_chat_warning_enabled() -> bool:
    _load_runtime_state()
    return bool(_RUNTIME_STATE["not_in_chat_warning"])


def set_not_in_chat_warning_enabled(enabled: bool) -> None:
    _RUNTIME_STATE["not_in_chat_warning"] = bool(enabled)
    _save_runtime_state()


def get_vip_enabled(user_id: int) -> bool:
    profile = get_profile(user_id)
    if not profile or not profile["vip_enabled"]:
        return False
    expires_at = profile["vip_expires_at"]
    if not expires_at:
        return True
    try:
        return datetime.fromisoformat(expires_at).astimezone(timezone.utc) > datetime.now(timezone.utc)
    except ValueError:
        return False


def set_vip_enabled(user_id: int, enabled: bool) -> None:
    ensure_user(user_id, f"User {user_id}") if get_profile(user_id) is None else None
    with _LOCK, get_connection() as conn:
        conn.execute(
            "UPDATE profiles SET vip_enabled = ?, vip_started_at = ?, vip_expires_at = ?, vip_source = ?, updated_at = ? WHERE user_id = ?",
            (1 if enabled else 0, _now() if enabled else None, None, "admin" if enabled else None, _now(), user_id),
        )
    _sync_runtime_user(user_id)


def grant_vip(
    user_id: int,
    days: int = 7,
    *,
    hours: int = 0,
    source: str = "telegram_stars",
    charge_id: str | None = None,
) -> str:
    ensure_user(user_id, f"User {user_id}") if get_profile(user_id) is None else None
    started_at = datetime.now(timezone.utc)
    profile = get_profile(user_id)
    if profile and profile["vip_expires_at"]:
        try:
            existing_expiry = datetime.fromisoformat(profile["vip_expires_at"]).astimezone(timezone.utc)
            if existing_expiry > started_at:
                started_at = existing_expiry
        except ValueError:
            pass
    expires_at = started_at + timedelta(days=days, hours=hours)
    with _LOCK, get_connection() as conn:
        conn.execute(
            "UPDATE profiles SET vip_enabled = 1, vip_started_at = ?, vip_expires_at = ?, vip_source = ?, last_payment_charge_id = ?, updated_at = ? WHERE user_id = ?",
            (datetime.now(timezone.utc).isoformat(), expires_at.isoformat(), source, charge_id, _now(), user_id),
        )
    _sync_runtime_user(user_id)
    return expires_at.isoformat()


def get_vip_expiry(user_id: int) -> str | None:
    profile = get_profile(user_id)
    return profile["vip_expires_at"] if profile else None


def record_vip_payment(
    user_id: int,
    charge_id: str,
    amount: int,
    payload: str,
    *,
    vip_started_at: str | None = None,
    vip_expires_at: str | None = None,
    vip_days: int | None = None,
) -> None:
    _RUNTIME_STATE["payments"].append({
        "uid": int(user_id),
        "charge_id": charge_id,
        "amount": int(amount),
        "currency": "XTR",
        "payload": payload,
        "paid_at": _now(),
        "vip_started_at": vip_started_at,
        "vip_expires_at": vip_expires_at,
        "vip_days": vip_days,
    })
    _save_runtime_state()


def get_referral_count(user_id: int) -> int:
    profile = get_profile(user_id)
    return int(profile["referral_count"] or 0) if profile else 0


def record_referral(referrer_id: int, referred_user_id: int) -> int:
    if referrer_id == referred_user_id:
        return get_referral_count(referrer_id)

    with _LOCK, get_connection() as conn:
        referrer = conn.execute(
            "SELECT user_id, referral_count FROM profiles WHERE user_id = ?",
            (referrer_id,),
        ).fetchone()
        referred = conn.execute(
            "SELECT referred_by FROM profiles WHERE user_id = ?",
            (referred_user_id,),
        ).fetchone()

        if referrer is None or referred is None:
            return 0
        if referred["referred_by"] is not None:
            return int(referrer["referral_count"] or 0)

        new_count = int(referrer["referral_count"] or 0) + 1
        conn.execute(
            "UPDATE profiles SET referral_count = ?, updated_at = ? WHERE user_id = ?",
            (new_count, _now(), referrer_id),
        )
        conn.execute(
            "UPDATE profiles SET referred_by = ?, updated_at = ? WHERE user_id = ?",
            (referrer_id, _now(), referred_user_id),
        )
        if new_count % 3 == 0:
            grant_vip(referrer_id, days=1, source="referral")
        return new_count


def profile_summary(user_id: int) -> str:
    profile = get_profile(user_id)
    if profile is None:
        return "No profile yet."

    age = profile["age"] if profile["age"] is not None else "Not set"
    gender = profile["gender"] or "unspecified"
    preferred_gender = profile["preferred_gender"] or "any"
    if profile["partner_age_min"] is not None and profile["partner_age_max"] is not None:
        age_range = f'{profile["partner_age_min"]}-{profile["partner_age_max"]}'
    else:
        age_range = "Any"
    vip_status = "On" if get_vip_enabled(user_id) else "Off"
    referrals = int(profile["referral_count"] or 0) if profile else 0

    return (
        f"Age: {age}\n"
        f"Gender: {gender}\n"
        f"Preferred partner gender: {preferred_gender}\n"
        f"Preferred partner age: {age_range}\n"
        f"VIP: {vip_status}\n"
        f"Referrals: {referrals}/3"
    )


def set_user_age(user_id: int, age: int) -> None:
    update_profile(user_id, age=age)


def set_user_gender(user_id: int, gender: str) -> None:
    update_profile(user_id, gender=gender)


def set_user_preferred_gender(user_id: int, preferred_gender: str) -> None:
    update_profile(user_id, preferred_gender=preferred_gender)


def set_user_partner_age_range(user_id: int, minimum: int | None, maximum: int | None) -> None:
    update_profile(user_id, partner_age_min=minimum, partner_age_max=maximum)


def set_verified_only(user_id: int, enabled: bool) -> None:
    update_profile(user_id, verified_only=1 if enabled else 0)


def clear_profile(user_id: int) -> None:
    with _LOCK, get_connection() as conn:
        conn.execute(
            """
            UPDATE profiles
            SET age = NULL,
                gender = 'unspecified',
                preferred_gender = 'any',
                partner_age_min = NULL,
                partner_age_max = NULL,
                verified_only = 0,
                vip_enabled = 0,
                vip_started_at = NULL,
                vip_expires_at = NULL,
                vip_source = NULL,
                last_payment_charge_id = NULL,
                referral_count = 0,
                referred_by = NULL,
                updated_at = ?
            WHERE user_id = ?
            """,
            (_now(), user_id),
        )


def _normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


def _profile_gender(profile_row) -> str:
    gender = _normalize_text(profile_row["gender"] if profile_row else None)
    return gender if gender else "unspecified"


def _profile_age(profile_row):
    if profile_row is None or profile_row["age"] is None:
        return None
    return int(profile_row["age"])


def _age_in_range(age, minimum, maximum) -> bool:
    if age is None:
        return minimum is None and maximum is None
    if minimum is not None and age < minimum:
        return False
    if maximum is not None and age > maximum:
        return False
    return True


def _gender_matches(preference: str, other_gender: str) -> bool:
    preference = _normalize_text(preference)
    other_gender = _normalize_text(other_gender)
    if preference in {"", "any", "all"}:
        return True
    if other_gender in {"", "unspecified"}:
        return False
    return preference == other_gender


def _has_age_preference(profile_row) -> bool:
    if profile_row is None:
        return False
    return profile_row["partner_age_min"] is not None or profile_row["partner_age_max"] is not None


def _effective_verified_only(profile_row) -> bool:
    return bool(profile_row and profile_row["verified_only"] and profile_row["verified"])


def _match_priority_score(user_row, candidate_row) -> int:
    if user_row is None or candidate_row is None:
        return -1

    user_profile = get_profile(user_row["user_id"])
    candidate_profile = get_profile(candidate_row["user_id"])
    if user_profile is None or candidate_profile is None:
        return -1

    score = 0

    user_gender = _profile_gender(user_profile)
    candidate_gender = _profile_gender(candidate_profile)
    user_pref_gender = user_profile["preferred_gender"] if user_profile else "any"
    candidate_pref_gender = candidate_profile["preferred_gender"] if candidate_profile else "any"

    if _gender_matches(user_pref_gender, candidate_gender):
        score += 3 if _normalize_text(user_pref_gender) not in {"", "any", "all"} else 1
    if _gender_matches(candidate_pref_gender, user_gender):
        score += 3 if _normalize_text(candidate_pref_gender) not in {"", "any", "all"} else 1

    user_age = _profile_age(user_profile)
    candidate_age = _profile_age(candidate_profile)
    user_min = user_profile["partner_age_min"]
    user_max = user_profile["partner_age_max"]
    candidate_min = candidate_profile["partner_age_min"]
    candidate_max = candidate_profile["partner_age_max"]

    if user_age is not None and _age_in_range(user_age, candidate_min, candidate_max):
        score += 2
    if candidate_age is not None and _age_in_range(candidate_age, user_min, user_max):
        score += 2

    if user_age is None and candidate_age is None and not _has_age_preference(user_profile) and not _has_age_preference(candidate_profile):
        score += 1

    return score


def is_match_compatible(user_row, candidate_row) -> bool:
    if user_row is None or candidate_row is None:
        return False

    user_profile = get_profile(user_row["user_id"])
    candidate_profile = get_profile(candidate_row["user_id"])

    user_age = _profile_age(user_profile)
    candidate_age = _profile_age(candidate_profile)
    user_gender = _profile_gender(user_profile)
    candidate_gender = _profile_gender(candidate_profile)

    user_pref_gender = user_profile["preferred_gender"] if user_profile else "any"
    candidate_pref_gender = candidate_profile["preferred_gender"] if candidate_profile else "any"

    user_min = user_profile["partner_age_min"] if user_profile else None
    user_max = user_profile["partner_age_max"] if user_profile else None
    candidate_min = candidate_profile["partner_age_min"] if candidate_profile else None
    candidate_max = candidate_profile["partner_age_max"] if candidate_profile else None
    candidate_verified_only = _effective_verified_only(candidate_profile)
    user_verified_only = _effective_verified_only(user_profile)
    candidate_verified = candidate_profile["verified"] if candidate_profile else 0
    user_verified = user_profile["verified"] if user_profile else 0
    return (
        _gender_matches(user_pref_gender, candidate_gender)
        and _gender_matches(candidate_pref_gender, user_gender)
        and (candidate_age is None or _age_in_range(candidate_age, user_min, user_max))
        and (user_age is None or _age_in_range(user_age, candidate_min, candidate_max))
        and (not user_verified_only or bool(candidate_verified))
        and (not candidate_verified_only or bool(user_verified))
    )


def set_waiting(user_id: int) -> None:
    with _LOCK, get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO queue (user_id, joined_at) VALUES (?, ?)",
            (user_id, _now()),
        )
        conn.execute(
            "UPDATE users SET status = 'waiting', partner_id = NULL, is_emergency = 0, updated_at = ? WHERE user_id = ?",
            (_now(), user_id),
        )


def remove_from_queue(user_id: int) -> None:
    with _LOCK, get_connection() as conn:
        conn.execute("DELETE FROM queue WHERE user_id = ?", (user_id,))


def get_queue_joined_at(user_id: int):
    with _LOCK, get_connection() as conn:
        row = conn.execute(
            "SELECT joined_at FROM queue WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row["joined_at"] if row else None


def set_emergency_match(user_id: int) -> None:
    with _LOCK, get_connection() as conn:
        fake_partner_id = -abs(int(user_id)) - 1
        conn.execute(
            "DELETE FROM queue WHERE user_id = ?",
            (user_id,),
        )
        conn.execute(
            """
            UPDATE users
            SET status = 'matched',
                partner_id = ?,
                is_emergency = 1,
                updated_at = ?
            WHERE user_id = ?
            """,
            (fake_partner_id, _now(), user_id),
        )


def clear_emergency_match(user_id: int) -> None:
    with _LOCK, get_connection() as conn:
        conn.execute(
            "UPDATE users SET is_emergency = 0, updated_at = ? WHERE user_id = ?",
            (_now(), user_id),
        )


def is_emergency_match(user_id: int) -> bool:
    row = get_user(user_id)
    return bool(row and row["is_emergency"])


def end_match(user_id: int) -> int | None:
    with _LOCK, get_connection() as conn:
        row = conn.execute(
            "SELECT partner_id, is_emergency FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        partner_id = row["partner_id"] if row and row["partner_id"] not in (None, 0) else None
        if row and row["is_emergency"]:
            partner_id = None
        conn.execute(
            "UPDATE users SET status = 'idle', partner_id = NULL, is_emergency = 0, updated_at = ? WHERE user_id = ?",
            (_now(), user_id),
        )
        if partner_id is not None:
            conn.execute(
                "UPDATE users SET status = 'idle', partner_id = NULL, is_emergency = 0, updated_at = ? WHERE user_id = ?",
                (_now(), partner_id),
            )
        return partner_id


def get_user(user_id: int):
    with _LOCK, get_connection() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()


def get_waiting_count() -> int:
    with _LOCK, get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM queue").fetchone()
        return int(row["count"])


def get_waiting_users():
    with _LOCK, get_connection() as conn:
        return conn.execute(
            """
            SELECT q.user_id, u.name, q.joined_at
            FROM queue q
            JOIN users u ON u.user_id = q.user_id
            ORDER BY q.joined_at ASC
            """
        ).fetchall()


def get_active_matches():
    with _LOCK, get_connection() as conn:
        return conn.execute(
            """
            SELECT u.user_id, u.name, u.partner_id, p.name AS partner_name, u.updated_at
            FROM users u
            LEFT JOIN users p ON p.user_id = u.partner_id
            WHERE u.status = 'matched' AND u.partner_id IS NOT NULL AND u.user_id < u.partner_id
            ORDER BY u.updated_at DESC
            """
        ).fetchall()


def get_active_user_ids():
    with _LOCK, get_connection() as conn:
        rows = conn.execute(
            """
            SELECT user_id
            FROM users
            WHERE status IN ('waiting', 'matched')
            ORDER BY updated_at DESC
            """
        ).fetchall()
        return [int(row["user_id"]) for row in rows]


def get_all_user_ids():
    with _LOCK, get_connection() as conn:
        rows = conn.execute(
            """
            SELECT user_id
            FROM users
            ORDER BY updated_at DESC
            """
        ).fetchall()
        return [int(row["user_id"]) for row in rows]


def log_message(sender_id: int, recipient_id: int, body: str) -> None:
    with _LOCK, get_connection() as conn:
        conn.execute(
            """
            INSERT INTO messages (sender_id, recipient_id, body, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (sender_id, recipient_id, body, _now()),
        )


def get_reality_score(user_id: int) -> int:
    profile = get_profile(user_id)
    if profile is None:
        return 0
    return int(profile["reality_score"] or 0)


def is_verified(user_id: int) -> bool:
    profile = get_profile(user_id)
    if profile is None:
        return False
    return bool(profile["verified"])


def set_verified(user_id: int, enabled: bool) -> None:
    with _LOCK, get_connection() as conn:
        conn.execute(
            "UPDATE profiles SET verified = ?, updated_at = ? WHERE user_id = ?",
            (1 if enabled else 0, _now(), user_id),
        )


def add_reality_score(user_id: int, delta: int) -> int:
    with _LOCK, get_connection() as conn:
        conn.execute(
            """
            UPDATE profiles
            SET reality_score = MAX(0, reality_score + ?),
                updated_at = ?
            WHERE user_id = ?
            """,
            (delta, _now(), user_id),
        )
        row = conn.execute(
            "SELECT reality_score FROM profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return int(row["reality_score"] if row else 0)


def request_verification(user_id: int) -> bool:
    score = get_reality_score(user_id)
    if score < 10:
        return False
    set_verified(user_id, True)
    return True


def get_verified_badge(user_id: int) -> str:
    return "✪ Verified" if is_verified(user_id) else "👤 Unverified"


def set_media_permission(user_id: int, partner_id: int, allowed: bool) -> None:
    low_id = min(user_id, partner_id)
    high_id = max(user_id, partner_id)
    with _LOCK, get_connection() as conn:
        conn.execute(
            """
            INSERT INTO media_permissions (low_user_id, high_user_id, allowed, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(low_user_id, high_user_id) DO UPDATE SET
                allowed = excluded.allowed,
                updated_at = excluded.updated_at
            """,
            (low_id, high_id, 1 if allowed else 0, _now()),
        )


def get_media_permission(user_id: int, partner_id: int) -> bool:
    low_id = min(user_id, partner_id)
    high_id = max(user_id, partner_id)
    with _LOCK, get_connection() as conn:
        row = conn.execute(
            "SELECT allowed FROM media_permissions WHERE low_user_id = ? AND high_user_id = ?",
            (low_id, high_id),
        ).fetchone()
        return bool(row["allowed"]) if row else False


def clear_pair_media_state(user_id: int, partner_id: int) -> None:
    low_id = min(user_id, partner_id)
    high_id = max(user_id, partner_id)
    with _LOCK, get_connection() as conn:
        conn.execute(
            "DELETE FROM media_permissions WHERE low_user_id = ? AND high_user_id = ?",
            (low_id, high_id),
        )
        conn.execute(
            "DELETE FROM pending_media WHERE (sender_id = ? AND recipient_id = ?) OR (sender_id = ? AND recipient_id = ?)",
            (user_id, partner_id, partner_id, user_id),
        )


def add_pending_media(sender_id: int, recipient_id: int, media_type: str, file_id: str, caption: str | None = None) -> int:
    with _LOCK, get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM pending_media WHERE sender_id = ? AND recipient_id = ?",
            (sender_id, recipient_id),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE pending_media
                SET media_type = ?, file_id = ?, caption = ?, created_at = ?
                WHERE sender_id = ? AND recipient_id = ?
                """,
                (media_type, file_id, caption, _now(), sender_id, recipient_id),
            )
            return int(existing["id"])
        cursor = conn.execute(
            """
            INSERT INTO pending_media (sender_id, recipient_id, media_type, file_id, caption, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (sender_id, recipient_id, media_type, file_id, caption, _now()),
        )
        return int(cursor.lastrowid)


def get_pending_media(sender_id: int, recipient_id: int):
    with _LOCK, get_connection() as conn:
        return conn.execute(
            """
            SELECT * FROM pending_media
            WHERE sender_id = ? AND recipient_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (sender_id, recipient_id),
        ).fetchone()


def pop_pending_media(sender_id: int, recipient_id: int):
    with _LOCK, get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM pending_media
            WHERE sender_id = ? AND recipient_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (sender_id, recipient_id),
        ).fetchone()
        if row:
            conn.execute(
                "DELETE FROM pending_media WHERE id = ?",
                (row["id"],),
            )
        return row


def get_pending_requests_for_recipient(recipient_id: int):
    with _LOCK, get_connection() as conn:
        return conn.execute(
            "SELECT * FROM pending_media WHERE recipient_id = ? ORDER BY created_at ASC",
            (recipient_id,),
        ).fetchall()


def add_feedback_prompt(rater_id: int, target_id: int) -> None:
    with _LOCK, get_connection() as conn:
        conn.execute(
            """
            INSERT INTO feedback_prompts (rater_id, target_id, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(rater_id) DO UPDATE SET
                target_id = excluded.target_id,
                created_at = excluded.created_at
            """,
            (rater_id, target_id, _now()),
        )


def get_feedback_prompt(rater_id: int):
    with _LOCK, get_connection() as conn:
        return conn.execute(
            "SELECT * FROM feedback_prompts WHERE rater_id = ?",
            (rater_id,),
        ).fetchone()


def pop_feedback_prompt(rater_id: int):
    with _LOCK, get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM feedback_prompts WHERE rater_id = ?",
            (rater_id,),
        ).fetchone()
        if row:
            conn.execute("DELETE FROM feedback_prompts WHERE rater_id = ?", (rater_id,))
        return row


def match_waiting_user(user_id: int):
    with _LOCK, get_connection() as conn:
        current = conn.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if current is None:
            return None

        if current["status"] == "matched":
            partner_row = conn.execute(
                "SELECT partner_id FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return {"partner_id": partner_row["partner_id"] if partner_row else None}

        waiting_rows = conn.execute(
            """
            SELECT q.user_id, q.joined_at
            FROM queue q
            JOIN users u ON u.user_id = q.user_id
            WHERE q.user_id != ?
            ORDER BY q.joined_at ASC
            """,
            (user_id,),
        ).fetchall()

        if not waiting_rows:
            conn.execute(
                "INSERT OR REPLACE INTO queue (user_id, joined_at) VALUES (?, ?)",
                (user_id, _now()),
            )
            conn.execute(
                "UPDATE users SET status = 'waiting', partner_id = NULL, updated_at = ? WHERE user_id = ?",
                (_now(), user_id),
            )
            return None

        user_row = current
        compatible_rows = []
        for row in waiting_rows:
            candidate_row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (row["user_id"],),
            ).fetchone()
            if is_match_compatible(user_row, candidate_row):
                compatible_rows.append(row)

        if not compatible_rows:
            conn.execute(
                "INSERT OR REPLACE INTO queue (user_id, joined_at) VALUES (?, ?)",
                (user_id, _now()),
            )
            conn.execute(
                "UPDATE users SET status = 'waiting', partner_id = NULL, updated_at = ? WHERE user_id = ?",
                (_now(), user_id),
            )
            return None

        user_profile = get_profile(user_id)
        if _effective_verified_only(user_profile):
            verified_rows = [row for row in compatible_rows if is_verified(row["user_id"])]
            chosen_pool = verified_rows or compatible_rows
        else:
            chosen_pool = compatible_rows

        top_score = max(_match_priority_score(user_row, row) for row in chosen_pool)
        scored_pool = [row for row in chosen_pool if _match_priority_score(user_row, row) == top_score]
        chosen_row = random.choice(scored_pool)
        partner_id = chosen_row["user_id"]
        partner_joined_at = chosen_row["joined_at"]
        user_joined_row = conn.execute(
            "SELECT joined_at FROM queue WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        user_joined_at = user_joined_row["joined_at"] if user_joined_row else _now()
        conn.execute("DELETE FROM queue WHERE user_id IN (?, ?)", (user_id, partner_id))
        conn.execute(
            "UPDATE users SET status = 'matched', partner_id = ?, is_emergency = 0, joined_at = COALESCE(joined_at, ?), updated_at = ? WHERE user_id = ?",
            (partner_id, _now(), _now(), user_id),
        )
        conn.execute(
            "UPDATE users SET status = 'matched', partner_id = ?, is_emergency = 0, joined_at = COALESCE(joined_at, ?), updated_at = ? WHERE user_id = ?",
            (user_id, _now(), _now(), partner_id),
        )
        return {
            "partner_id": partner_id,
            "user_joined_at": user_joined_at,
            "partner_joined_at": partner_joined_at,
        }


def reset_all() -> None:
    with _LOCK, get_connection() as conn:
        conn.execute("DELETE FROM queue")
        conn.execute("UPDATE users SET status = 'idle', partner_id = NULL, joined_at = NULL, updated_at = ?", (_now(),))
