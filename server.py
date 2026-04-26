#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from datetime import datetime, timezone
from http import cookies
import json
import os
import hashlib
import hmac
import secrets

import psycopg
from psycopg.rows import dict_row

from store_scrapers import fetch_product_snapshot


def load_env_file():
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


load_env_file()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "pricecompare")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8080"))
SESSION_COOKIE_NAME = "pricewatch_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
FRONTEND_ORIGINS = {
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:8080,http://localhost:8080",
    ).split(",")
    if origin.strip()
}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def get_conn():
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        row_factory=dict_row,
    )


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    email TEXT UNIQUE,
                    first_name TEXT,
                    last_name TEXT,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    external_product_id TEXT NOT NULL UNIQUE,
                    product_url TEXT NOT NULL,
                    name TEXT,
                    brand TEXT,
                    current_price DOUBLE PRECISION,
                    original_price DOUBLE PRECISION,
                    was_price DOUBLE PRECISION,
                    cup_price TEXT,
                    in_stock BOOLEAN,
                    image_url TEXT,
                    last_checked_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_watchlists (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    last_seen_price DOUBLE PRECISION,
                    last_notified_price DOUBLE PRECISION,
                    notify_on_drop BOOLEAN NOT NULL DEFAULT TRUE,
                    notify_on_increase BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS product_price_history (
                    id SERIAL PRIMARY KEY,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    price DOUBLE PRECISION,
                    was_price DOUBLE PRECISION,
                    in_stock BOOLEAN,
                    recorded_at TIMESTAMPTZ NOT NULL
                );
            """)

            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                                                FROM information_schema.tables
                                                WHERE table_schema = 'public'
                                                    AND table_name = 'watched_products'
                                                    AND table_type = 'BASE TABLE'
                    ) AND NOT EXISTS (
                        SELECT 1
                                                FROM pg_class c
                                                JOIN pg_namespace n ON n.oid = c.relnamespace
                                                WHERE n.nspname = 'public'
                                                    AND c.relname = 'watched_products_legacy'
                    ) THEN
                        ALTER TABLE watched_products RENAME TO watched_products_legacy;
                    END IF;
                END
                $$;
            """)

            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                                                FROM information_schema.tables
                                                WHERE table_schema = 'public'
                                                    AND table_name = 'price_history'
                                                    AND table_type = 'BASE TABLE'
                    ) AND NOT EXISTS (
                        SELECT 1
                                                FROM pg_class c
                                                JOIN pg_namespace n ON n.oid = c.relnamespace
                                                WHERE n.nspname = 'public'
                                                    AND c.relname = 'price_history_legacy'
                    ) THEN
                        ALTER TABLE price_history RENAME TO price_history_legacy;
                    END IF;
                END
                $$;
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS products_last_checked_idx
                ON products(last_checked_at)
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS watchlists_scope_idx
                ON user_watchlists ((COALESCE(user_id, 0)), active, created_at DESC)
            """)

            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS user_watchlists_scope_product_idx
                ON user_watchlists ((COALESCE(user_id, 0)), product_id)
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS watchlists_product_idx
                ON user_watchlists(product_id, active)
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS product_price_history_product_idx
                ON product_price_history(product_id, recorded_at DESC)
            """)

            cur.execute("""
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS original_price DOUBLE PRECISION
            """)

            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relname = 'watched_products_legacy'
                      AND c.relkind = 'r'
                ) AS legacy_table
            """)
            watched_products_legacy = cur.fetchone()["legacy_table"]

            if watched_products_legacy:
                cur.execute("""
                    ALTER TABLE watched_products_legacy
                    ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE
                """)

                cur.execute("""
                    INSERT INTO products (
                        external_product_id,
                        product_url,
                        name,
                        brand,
                        current_price,
                        original_price,
                        was_price,
                        cup_price,
                        in_stock,
                        image_url,
                        last_checked_at,
                        created_at,
                        updated_at
                    )
                    SELECT
                        wp.product_id,
                        wp.product_url,
                        wp.name,
                        wp.brand,
                        wp.current_price,
                        COALESCE(wp.was_price, wp.current_price),
                        wp.was_price,
                        wp.cup_price,
                        wp.in_stock,
                        wp.image_url,
                        wp.last_checked_at,
                        wp.created_at,
                        COALESCE(wp.last_checked_at, wp.created_at)
                    FROM watched_products_legacy wp
                    ON CONFLICT (external_product_id) DO NOTHING
                """)

                cur.execute("""
                    INSERT INTO user_watchlists (
                        user_id,
                        product_id,
                        created_at,
                        last_seen_price
                    )
                    SELECT
                        wp.user_id,
                        p.id,
                        wp.created_at,
                        wp.current_price
                    FROM watched_products_legacy wp
                    JOIN products p ON p.external_product_id = wp.product_id
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM user_watchlists existing
                        WHERE existing.user_id IS NOT DISTINCT FROM wp.user_id
                          AND existing.product_id = p.id
                    )
                """)

            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relname = 'price_history_legacy'
                      AND c.relkind = 'r'
                ) AS legacy_table
            """)
            price_history_legacy = cur.fetchone()["legacy_table"]

            if price_history_legacy:
                cur.execute("""
                    ALTER TABLE price_history_legacy
                    ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE
                """)

                cur.execute("""
                    INSERT INTO product_price_history (
                        product_id,
                        price,
                        was_price,
                        in_stock,
                        recorded_at
                    )
                    SELECT DISTINCT
                        p.id,
                        ph.price,
                        prod.was_price,
                        prod.in_stock,
                        ph.recorded_at
                    FROM price_history_legacy ph
                    JOIN products p ON p.external_product_id = ph.product_id
                    LEFT JOIN watched_products_legacy prod
                        ON prod.product_id = ph.product_id
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM product_price_history existing
                        WHERE existing.product_id = p.id
                          AND existing.recorded_at = ph.recorded_at
                          AND existing.price IS NOT DISTINCT FROM ph.price
                    )
                """)

            cur.execute("""
                UPDATE products
                SET original_price = was_price
                WHERE original_price IS DISTINCT FROM was_price
            """)

            cur.execute("DROP VIEW IF EXISTS watched_products")
            cur.execute("""
                CREATE VIEW watched_products AS
                SELECT
                    p.id,
                    p.external_product_id AS product_id,
                    p.product_url,
                    p.name,
                    p.brand,
                    p.current_price,
                    p.original_price,
                    prev.price AS previous_price,
                    p.was_price,
                    p.cup_price,
                    p.in_stock,
                    p.image_url,
                    p.last_checked_at,
                    CASE
                        WHEN prev.price IS NOT NULL
                             AND p.current_price IS NOT NULL
                             AND p.current_price < prev.price
                        THEN TRUE ELSE FALSE
                    END AS has_drop,
                    p.created_at,
                    NULL::INTEGER AS user_id
                FROM products p
                LEFT JOIN LATERAL (
                    SELECT ph.price
                    FROM product_price_history ph
                    WHERE ph.product_id = p.id
                    ORDER BY ph.recorded_at DESC, ph.id DESC
                    OFFSET 1 LIMIT 1
                ) prev ON TRUE
            """)

            cur.execute("DROP VIEW IF EXISTS price_history")
            cur.execute("""
                CREATE VIEW price_history AS
                SELECT
                    ph.id,
                    NULL::INTEGER AS user_id,
                    p.external_product_id AS product_id,
                    ph.price,
                    ph.recorded_at
                FROM product_price_history ph
                JOIN products p ON p.id = ph.product_id
            """)
        conn.commit()


def normalise_username(value):
    value = (value or "").strip().lower()
    return value or None


def normalise_email(value):
    value = (value or "").strip().lower()
    return value or None


def hash_password(password, *, salt=None):
    if not password:
        raise ValueError("Password is required.")
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"{salt.hex()}${derived.hex()}"


def verify_password(password, stored_hash):
    try:
        salt_hex, digest_hex = stored_hash.split("$", 1)
    except ValueError:
        return False
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        200_000,
    )
    return hmac.compare_digest(actual, expected)


def sanitise_user_row(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "created_at": row["created_at"],
    }


def create_user(*, username, email, first_name, last_name, password):
    username = normalise_username(username)
    email = normalise_email(email)
    first_name = (first_name or "").strip() or None
    last_name = (last_name or "").strip() or None

    if not username:
        raise ValueError("Username is required.")
    if len(password or "") < 6:
        raise ValueError("Password must be at least 6 characters.")

    password_hash = hash_password(password)
    now = utc_now()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (username, email, first_name, last_name, password_hash, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, username, email, first_name, last_name, created_at
                """,
                (username, email, first_name, last_name, password_hash, now),
            )
            user = cur.fetchone()
        conn.commit()
    return user


def authenticate_user(*, identifier, password):
    identifier = (identifier or "").strip().lower()
    if not identifier or not password:
        raise ValueError("Username/email and password are required.")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, username, email, first_name, last_name, password_hash, created_at
                FROM users
                WHERE username = %s OR email = %s
                LIMIT 1
                """,
                (identifier, identifier),
            )
            user = cur.fetchone()

    if not user or not verify_password(password, user["password_hash"]):
        raise ValueError("Invalid username/email or password.")
    return user


def create_session(user_id):
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = utc_now()
    expires_at = datetime.fromtimestamp(
        now.timestamp() + SESSION_TTL_SECONDS,
        tz=timezone.utc,
    ).replace(microsecond=0)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_sessions (user_id, token_hash, created_at, expires_at)
                VALUES (%s, %s, %s, %s)
                """,
                (user_id, token_hash, now, expires_at),
            )
        conn.commit()

    return raw_token, expires_at


def get_user_by_session_token(raw_token):
    if not raw_token:
        return None

    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = utc_now()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.username, u.email, u.first_name, u.last_name, u.created_at
                FROM user_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = %s AND s.expires_at > %s
                LIMIT 1
                """,
                (token_hash, now),
            )
            return cur.fetchone()


def revoke_session(raw_token):
    if not raw_token:
        return
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_sessions WHERE token_hash = %s",
                (token_hash,),
            )
        conn.commit()


def upsert_product_snapshot(snapshot):
    now = utc_now()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, current_price, original_price
                FROM products
                WHERE external_product_id = %s
                """,
                (snapshot.product_id,),
            )
            existing = cur.fetchone()

            if existing:
                old_price = existing["current_price"]
                cur.execute(
                    """
                    UPDATE products
                    SET
                        product_url = %s,
                        name = %s,
                        brand = %s,
                        current_price = %s,
                        original_price = %s,
                        was_price = %s,
                        cup_price = %s,
                        in_stock = %s,
                        image_url = %s,
                        last_checked_at = %s,
                        updated_at = %s
                    WHERE id = %s
                    RETURNING id, external_product_id, current_price, original_price, was_price, cup_price,
                              in_stock, image_url, product_url, name, brand, last_checked_at,
                              created_at, updated_at
                    """,
                    (
                        snapshot.canonical_url,
                        snapshot.name,
                        snapshot.brand,
                        snapshot.price,
                        snapshot.was_price,
                        snapshot.was_price,
                        snapshot.cup_price,
                        snapshot.in_stock,
                        snapshot.image_url,
                        now,
                        now,
                        existing["id"],
                    ),
                )
                product = cur.fetchone()
            else:
                old_price = None
                cur.execute(
                    """
                    INSERT INTO products (
                        external_product_id,
                        product_url,
                        name,
                        brand,
                        current_price,
                        original_price,
                        was_price,
                        cup_price,
                        in_stock,
                        image_url,
                        last_checked_at,
                        created_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, external_product_id, current_price, original_price, was_price, cup_price,
                              in_stock, image_url, product_url, name, brand, last_checked_at,
                              created_at, updated_at
                    """,
                    (
                        snapshot.product_id,
                        snapshot.canonical_url,
                        snapshot.name,
                        snapshot.brand,
                        snapshot.price,
                        snapshot.was_price,
                        snapshot.was_price,
                        snapshot.cup_price,
                        snapshot.in_stock,
                        snapshot.image_url,
                        now,
                        now,
                        now,
                    ),
                )
                product = cur.fetchone()

            cur.execute(
                """
                SELECT price
                FROM product_price_history
                WHERE product_id = %s
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
                """,
                (product["id"],),
            )
            latest_history = cur.fetchone()

            if latest_history is None or latest_history["price"] != snapshot.price:
                cur.execute(
                    """
                    INSERT INTO product_price_history (product_id, price, was_price, in_stock, recorded_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (product["id"], snapshot.price, snapshot.was_price, snapshot.in_stock, now),
                )

        conn.commit()

    return product, old_price


def add_product_to_watchlist(snapshot, *, user_id=None):
    product, _ = upsert_product_snapshot(snapshot)
    now = utc_now()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_watchlists (
                    user_id,
                    product_id,
                    created_at,
                    last_seen_price
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT ((COALESCE(user_id, 0)), product_id)
                DO UPDATE SET active = TRUE
                RETURNING id
                """,
                (user_id, product["id"], now, product["current_price"]),
            )
            cur.fetchone()
        conn.commit()

    return product


def list_products(*, user_id=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    uw.id AS watchlist_id,
                    uw.user_id,
                    uw.created_at,
                    uw.last_seen_price,
                    p.id AS product_db_id,
                    p.external_product_id AS product_id,
                    p.product_url,
                    p.name,
                    p.brand,
                    p.current_price,
                    p.original_price,
                    prev.price AS previous_price,
                    p.was_price,
                    p.cup_price,
                    p.in_stock,
                    p.image_url,
                    p.last_checked_at,
                    CASE
                        WHEN prev.price IS NOT NULL AND p.current_price IS NOT NULL AND p.current_price < prev.price
                        THEN TRUE ELSE FALSE
                    END AS has_drop
                FROM user_watchlists uw
                JOIN products p ON p.id = uw.product_id
                LEFT JOIN LATERAL (
                    SELECT ph.price
                    FROM product_price_history ph
                    WHERE ph.product_id = p.id
                    ORDER BY ph.recorded_at DESC, ph.id DESC
                    OFFSET 1 LIMIT 1
                ) prev ON TRUE
                WHERE uw.user_id IS NOT DISTINCT FROM %s
                  AND uw.active = TRUE
                ORDER BY
                    CASE
                        WHEN prev.price IS NOT NULL AND p.current_price IS NOT NULL AND p.current_price < prev.price
                        THEN 1 ELSE 0
                    END DESC,
                    uw.created_at DESC
                """,
                (user_id,),
            )
            return cur.fetchall()


def remove_product(product_id, *, user_id=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_watchlists uw
                SET active = FALSE
                FROM products p
                WHERE uw.product_id = p.id
                  AND p.external_product_id = %s
                  AND uw.user_id IS NOT DISTINCT FROM %s
                """,
                (product_id, user_id),
            )
        conn.commit()


def get_price_history(product_id, *, user_id=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ph.price, ph.recorded_at
                FROM products p
                JOIN user_watchlists uw ON uw.product_id = p.id
                JOIN product_price_history ph ON ph.product_id = p.id
                WHERE p.external_product_id = %s
                  AND uw.user_id IS NOT DISTINCT FROM %s
                  AND uw.active = TRUE
                ORDER BY ph.recorded_at ASC, ph.id ASC
                """,
                (product_id, user_id),
            )
            return cur.fetchall()


def refresh_all_products(*, user_id=None, all_scopes=False):
    if all_scopes:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT
                        p.external_product_id AS product_id,
                        p.product_url,
                        p.name,
                        p.current_price
                    FROM user_watchlists uw
                    JOIN products p ON p.id = uw.product_id
                    WHERE uw.active = TRUE
                    """
                )
                products = cur.fetchall()
    else:
        products = list_products(user_id=user_id)
    drops = []
    increases = []
    errors = []
    updated = []

    seen = set()
    for p in products:
        if p["product_id"] in seen:
            continue
        seen.add(p["product_id"])
        try:
            snapshot = fetch_product_snapshot(p["product_url"])
            old_price = p["current_price"]
            upsert_product_snapshot(snapshot)

            has_drop = (
                old_price is not None
                and snapshot.price is not None
                and snapshot.price < old_price
            )
            has_increase = (
                old_price is not None
                and snapshot.price is not None
                and snapshot.price > old_price
            )

            entry = {
                "product_id": snapshot.product_id,
                "name": snapshot.name,
                "old_price": old_price,
                "new_price": snapshot.price,
                "has_drop": has_drop,
                "has_increase": has_increase,
            }

            updated.append(entry)
            if has_drop:
                drops.append(entry)
            if has_increase:
                increases.append(entry)

        except Exception as exc:
            errors.append(
                {"product_id": p["product_id"], "error": str(exc)}
            )

    return {
        "updated": updated,
        "drops": drops,
        "increases": increases,
        "errors": errors,
    }


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        current_user = self._get_current_user()
        current_user_id = current_user["id"] if current_user else None

        if parsed.path in ("/", "/dashboard", "/pricecompare.html"):
            self._send(
                200,
                {
                    "message": "PriceWatch backend API is running.",
                    "frontend": "Use the Next.js app at http://127.0.0.1:3000",
                },
            )
            return

        if parsed.path == "/product":
            target = (params.get("target") or [""])[0].strip()
            if not target:
                self._send(400, {"error": "missing ?target="})
                return
            try:
                snapshot = fetch_product_snapshot(target)
                self._send(200, snapshot.to_dict())
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/save":
            target = (params.get("target") or [""])[0].strip()
            if not target:
                self._send(400, {"error": "missing ?target="})
                return
            try:
                snapshot = fetch_product_snapshot(target)
                add_product_to_watchlist(snapshot, user_id=current_user_id)
                self._send(200, snapshot.to_dict())
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/watchlist":
            try:
                self._send(200, {"products": list_products(user_id=current_user_id)})
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/refresh-all":
            try:
                self._send(200, refresh_all_products(user_id=current_user_id))
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/remove":
            product_id = (params.get("product_id") or [""])[0].strip()
            if not product_id:
                self._send(400, {"error": "missing ?product_id="})
                return
            try:
                remove_product(product_id, user_id=current_user_id)
                self._send(200, {"ok": True})
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/history":
            product_id = (params.get("product_id") or [""])[0].strip()
            if not product_id:
                self._send(400, {"error": "missing ?product_id="})
                return
            try:
                self._send(200, {"history": get_price_history(product_id, user_id=current_user_id)})
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/auth/me":
            user = self._get_current_user()
            self._send(200, {"user": sanitise_user_row(user)})
            return

        self._send(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        payload = self._read_json_body()

        if parsed.path == "/auth/signup":
            try:
                password = (payload.get("password") or "").strip()
                confirm_password = (payload.get("confirm_password") or "").strip()
                if password != confirm_password:
                    raise ValueError("Passwords do not match.")
                user = create_user(
                    username=payload.get("username"),
                    email=payload.get("email"),
                    first_name=payload.get("first_name"),
                    last_name=payload.get("last_name"),
                    password=password,
                )
                token, expires_at = create_session(user["id"])
                self._send(
                    200,
                    {"user": sanitise_user_row(user)},
                    headers=self._session_headers(token, expires_at),
                )
            except psycopg.errors.UniqueViolation:
                self._send(400, {"error": "That username or email is already in use."})
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/auth/login":
            try:
                user = authenticate_user(
                    identifier=payload.get("identifier"),
                    password=(payload.get("password") or "").strip(),
                )
                token, expires_at = create_session(user["id"])
                self._send(
                    200,
                    {"user": sanitise_user_row(user)},
                    headers=self._session_headers(token, expires_at),
                )
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/auth/logout":
            try:
                revoke_session(self._get_session_token())
                self._send(
                    200,
                    {"ok": True},
                    headers=self._clear_session_headers(),
                )
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        self._send(404, {"error": "not found"})

    def _json_default(self, value):
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(
            f"Object of type {type(value).__name__} is not JSON serializable"
        )

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _get_session_token(self):
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None
        jar = cookies.SimpleCookie()
        jar.load(cookie_header)
        morsel = jar.get(SESSION_COOKIE_NAME)
        return morsel.value if morsel else None

    def _get_current_user(self):
        return get_user_by_session_token(self._get_session_token())

    def _session_headers(self, token, expires_at):
        return {
            "Set-Cookie": (
                f"{SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; "
                f"Expires={expires_at.strftime('%a, %d %b %Y %H:%M:%S GMT')}"
            )
        }

    def _clear_session_headers(self):
        return {
            "Set-Cookie": (
                f"{SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; "
                "Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            )
        }

    def _send_cors_headers(self):
        origin = self.headers.get("Origin")
        if origin in FRONTEND_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")

    def _send(self, status, data, *, headers=None):
        body = json.dumps(data, default=self._json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._send_cors_headers()
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    init_db()
    print(
        f"Running at http://{APP_HOST}:{APP_PORT} using PostgreSQL database '{DB_NAME}'"
    )
    HTTPServer((APP_HOST, APP_PORT), Handler).serve_forever()
