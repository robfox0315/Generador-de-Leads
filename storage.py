"""
Almacenamiento persistente de LeadForge.

Guarda los leads en SQLite para que sobrevivan entre sesiones, evita duplicados
automáticamente y permite seguir el estado comercial de cada contacto.

Aviso sobre despliegues en la nube:
    Streamlit Community Cloud usa un sistema de archivos efímero: la base se
    reinicia con cada redespliegue. Usa el botón de copia de seguridad para
    descargar tus datos, o apunta LEADFORGE_DB a un volumen persistente.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterable

DB_PATH = os.environ.get("LEADFORGE_DB", "leadforge.db")
_lock = threading.Lock()

STATUSES = ("Pendiente", "Contactado", "Respondió", "Demo agendada",
            "Cliente", "Descartado")

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint     TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    sport           TEXT,
    country         TEXT,
    city            TEXT,
    province        TEXT,
    address         TEXT,
    phone_display   TEXT,
    phone_e164      TEXT,
    phone_kind      TEXT,
    whatsapp_url    TEXT,
    website         TEXT,
    domain          TEXT,
    email           TEXT,
    email_type      TEXT,
    contact_name    TEXT,
    contact_role    TEXT,
    rating          TEXT,
    maps_url        TEXT,
    message         TEXT,
    size_hint       TEXT,
    score           INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'Pendiente',
    notes           TEXT DEFAULT '',
    campaign        TEXT DEFAULT '',
    created_at      TEXT,
    updated_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_leads_status   ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_phone    ON leads(phone_e164);
CREATE INDEX IF NOT EXISTS idx_leads_campaign ON leads(campaign);

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id    INTEGER,
    kind       TEXT,
    detail     TEXT,
    created_at TEXT,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);
"""

FIELDS = ("name", "sport", "country", "city", "province", "address", "phone_display",
          "phone_e164", "phone_kind", "whatsapp_url", "website", "domain", "email",
          "email_type", "contact_name", "contact_role", "rating", "maps_url",
          "message", "size_hint")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(path: str = DB_PATH):
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db(path: str = DB_PATH) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Huella y puntuación
# ---------------------------------------------------------------------------

def fingerprint(lead: dict) -> str:
    """Identidad estable de un lead: teléfono si existe, si no nombre+ciudad."""
    from lead_engine import normalize_key
    phone = (lead.get("phone_e164") or "").strip()
    if phone:
        return f"tel:{phone}"
    return f"name:{normalize_key(lead.get('name', ''))}|{normalize_key(lead.get('city', ''))}"


def score_lead(lead: dict) -> int:
    """
    Puntúa 0-100 la calidad del lead según lo que sabemos de él.
    No mide la probabilidad de compra: mide cuánta información accionable hay.
    """
    score = 0
    if str(lead.get("phone_kind", "")).startswith("Móvil"):
        score += 30          # se puede usar WhatsApp
    elif lead.get("phone_e164"):
        score += 15          # solo llamada
    if lead.get("email"):
        score += 20
        if lead.get("email_type") == "Personal":
            score += 5       # llega a una persona, no a un buzón
    if lead.get("contact_name"):
        score += 20          # sabemos con quién hablar
    if lead.get("website"):
        score += 10
    if lead.get("sport") and lead.get("sport") != "Multideporte":
        score += 10          # sabemos su nicho, el mensaje puede ser específico
    try:
        if float(lead.get("rating") or 0) >= 4.0:
            score += 5       # negocio activo y cuidado
    except (TypeError, ValueError):
        pass
    return min(100, score)


# ---------------------------------------------------------------------------
# Altas
# ---------------------------------------------------------------------------

def save_leads(leads: Iterable[dict], campaign: str = "",
               path: str = DB_PATH) -> dict:
    """Guarda leads evitando duplicados. Devuelve conteo de nuevos y repetidos."""
    init_db(path)
    inserted = duplicated = updated = 0
    stamp = _now()

    with _lock, connect(path) as conn:
        for lead in leads:
            mark = fingerprint(lead)
            existing = conn.execute(
                "SELECT id, email, contact_name FROM leads WHERE fingerprint = ?",
                (mark,)).fetchone()

            if existing:
                # Completa huecos si esta pasada trae más información
                patch, values = [], []
                if lead.get("email") and not existing["email"]:
                    patch.append("email = ?"); values.append(lead["email"])
                if lead.get("contact_name") and not existing["contact_name"]:
                    patch.append("contact_name = ?"); values.append(lead["contact_name"])
                if patch:
                    patch.append("updated_at = ?"); values.append(stamp)
                    values.append(existing["id"])
                    conn.execute(f"UPDATE leads SET {', '.join(patch)} WHERE id = ?", values)
                    updated += 1
                else:
                    duplicated += 1
                continue

            payload = {field: lead.get(field, "") for field in FIELDS}
            columns = ", ".join(("fingerprint", *FIELDS, "score", "campaign",
                                 "created_at", "updated_at"))
            marks = ", ".join("?" * (len(FIELDS) + 5))
            conn.execute(
                f"INSERT INTO leads ({columns}) VALUES ({marks})",
                (mark, *[payload[f] for f in FIELDS], score_lead(lead),
                 campaign, stamp, stamp),
            )
            inserted += 1

    return {"nuevos": inserted, "duplicados": duplicated, "completados": updated}


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def fetch_leads(status: str = "", campaign: str = "", search: str = "",
                limit: int = 5000, path: str = DB_PATH) -> list[dict]:
    init_db(path)
    query = "SELECT * FROM leads WHERE 1=1"
    params: list = []
    if status:
        query += " AND status = ?"; params.append(status)
    if campaign:
        query += " AND campaign = ?"; params.append(campaign)
    if search:
        query += " AND (name LIKE ? OR city LIKE ? OR province LIKE ?)"
        params += [f"%{search}%"] * 3
    query += " ORDER BY score DESC, created_at DESC LIMIT ?"
    params.append(limit)
    with connect(path) as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def known_fingerprints(path: str = DB_PATH) -> tuple[set[str], set[str]]:
    """Devuelve (claves de nombre, teléfonos) ya guardados, para excluirlos."""
    init_db(path)
    from lead_engine import normalize_key
    names: set[str] = set()
    phones: set[str] = set()
    with connect(path) as conn:
        for row in conn.execute("SELECT name, phone_e164 FROM leads"):
            if row["name"]:
                names.add(normalize_key(row["name"]))
            if row["phone_e164"]:
                phones.add(row["phone_e164"])
    return names, phones


def campaigns(path: str = DB_PATH) -> list[str]:
    init_db(path)
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT campaign FROM leads WHERE campaign != '' ORDER BY campaign"
        ).fetchall()
    return [row["campaign"] for row in rows]


def stats(path: str = DB_PATH) -> dict:
    init_db(path)
    with connect(path) as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM leads").fetchone()["n"]
        by_status = {row["status"]: row["n"] for row in conn.execute(
            "SELECT status, COUNT(*) AS n FROM leads GROUP BY status")}
        with_wa = conn.execute(
            "SELECT COUNT(*) AS n FROM leads WHERE phone_kind LIKE 'Móvil%'").fetchone()["n"]
        with_mail = conn.execute(
            "SELECT COUNT(*) AS n FROM leads WHERE email != ''").fetchone()["n"]
        with_person = conn.execute(
            "SELECT COUNT(*) AS n FROM leads WHERE contact_name != ''").fetchone()["n"]
        avg = conn.execute("SELECT AVG(score) AS s FROM leads").fetchone()["s"] or 0
        top_cities = [dict(row) for row in conn.execute(
            "SELECT city, COUNT(*) AS n FROM leads WHERE city != '' "
            "GROUP BY city ORDER BY n DESC LIMIT 8")]
    return {"total": total, "por_estado": by_status, "con_whatsapp": with_wa,
            "con_email": with_mail, "con_responsable": with_person,
            "score_medio": round(avg), "top_ciudades": top_cities}


# ---------------------------------------------------------------------------
# Actualizaciones
# ---------------------------------------------------------------------------

def update_status(lead_ids: Iterable[int], status: str, note: str = "",
                  path: str = DB_PATH) -> int:
    if status not in STATUSES:
        raise ValueError(f"Estado no válido: {status}")
    ids = list(lead_ids)
    if not ids:
        return 0
    stamp = _now()
    with _lock, connect(path) as conn:
        marks = ",".join("?" * len(ids))
        conn.execute(f"UPDATE leads SET status = ?, updated_at = ? WHERE id IN ({marks})",
                     [status, stamp, *ids])
        for lead_id in ids:
            conn.execute(
                "INSERT INTO events (lead_id, kind, detail, created_at) VALUES (?,?,?,?)",
                (lead_id, "estado", f"{status}{': ' + note if note else ''}", stamp))
    return len(ids)


def delete_leads(lead_ids: Iterable[int], path: str = DB_PATH) -> int:
    ids = list(lead_ids)
    if not ids:
        return 0
    with _lock, connect(path) as conn:
        marks = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM leads WHERE id IN ({marks})", ids)
    return len(ids)


def reset_database(path: str = DB_PATH) -> None:
    with _lock, connect(path) as conn:
        conn.executescript("DROP TABLE IF EXISTS events; DROP TABLE IF EXISTS leads;")
        conn.executescript(SCHEMA)


def export_all(path: str = DB_PATH) -> list[dict]:
    return fetch_leads(limit=100000, path=path)
