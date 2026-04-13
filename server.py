#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from datetime import datetime, timezone
import json
import os

import psycopg
from psycopg.rows import dict_row

from woolworths_scraper import fetch_product_snapshot


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
                CREATE TABLE IF NOT EXISTS watched_products (
                    id SERIAL PRIMARY KEY,
                    product_id TEXT NOT NULL UNIQUE,
                    product_url TEXT NOT NULL,
                    name TEXT,
                    brand TEXT,
                    current_price DOUBLE PRECISION,
                    previous_price DOUBLE PRECISION,
                    was_price DOUBLE PRECISION,
                    cup_price TEXT,
                    in_stock BOOLEAN,
                    image_url TEXT,
                    last_checked_at TIMESTAMPTZ,
                    has_drop BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id SERIAL PRIMARY KEY,
                    product_id TEXT NOT NULL,
                    price DOUBLE PRECISION,
                    recorded_at TIMESTAMPTZ NOT NULL
                );
            """)
        conn.commit()


def save_product(snapshot):
    now = utc_now()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, current_price
                FROM watched_products
                WHERE product_id = %s
                """,
                (snapshot.product_id,),
            )
            existing = cur.fetchone()

            if existing:
                old_price = existing["current_price"]
                has_drop = (
                    old_price is not None
                    and snapshot.price is not None
                    and snapshot.price < old_price
                )

                cur.execute(
                    """
                    UPDATE watched_products
                    SET
                        product_url = %s,
                        name = %s,
                        brand = %s,
                        previous_price = %s,
                        current_price = %s,
                        was_price = %s,
                        cup_price = %s,
                        in_stock = %s,
                        image_url = %s,
                        last_checked_at = %s,
                        has_drop = CASE WHEN %s THEN TRUE ELSE has_drop END
                    WHERE product_id = %s
                    """,
                    (
                        snapshot.canonical_url,
                        snapshot.name,
                        snapshot.brand,
                        old_price,
                        snapshot.price,
                        snapshot.was_price,
                        snapshot.cup_price,
                        snapshot.in_stock,
                        snapshot.image_url,
                        now,
                        has_drop,
                        snapshot.product_id,
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO watched_products (
                        product_id,
                        product_url,
                        name,
                        brand,
                        current_price,
                        previous_price,
                        was_price,
                        cup_price,
                        in_stock,
                        image_url,
                        last_checked_at,
                        has_drop,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s)
                    """,
                    (
                        snapshot.product_id,
                        snapshot.canonical_url,
                        snapshot.name,
                        snapshot.brand,
                        snapshot.price,
                        None,
                        snapshot.was_price,
                        snapshot.cup_price,
                        snapshot.in_stock,
                        snapshot.image_url,
                        now,
                        now,
                    ),
                )

            cur.execute(
                """
                INSERT INTO price_history (product_id, price, recorded_at)
                VALUES (%s, %s, %s)
                """,
                (snapshot.product_id, snapshot.price, now),
            )

        conn.commit()


def list_products():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT *
                FROM watched_products
                ORDER BY has_drop DESC, created_at DESC
            """)
            return cur.fetchall()


def remove_product(product_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM watched_products WHERE product_id = %s",
                (product_id,),
            )
            cur.execute(
                "DELETE FROM price_history WHERE product_id = %s",
                (product_id,),
            )
        conn.commit()


def get_price_history(product_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT price, recorded_at
                FROM price_history
                WHERE product_id = %s
                ORDER BY recorded_at ASC
                """,
                (product_id,),
            )
            return cur.fetchall()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path in ("/", "/pricecompare.html"):
            html = (Path(__file__).parent / "pricecompare.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(html)
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
                save_product(snapshot)
                self._send(200, snapshot.to_dict())
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/watchlist":
            try:
                self._send(200, {"products": list_products()})
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/refresh-all":
            try:
                products = list_products()
                drops = []
                errors = []
                updated = []

                for p in products:
                    try:
                        snapshot = fetch_product_snapshot(p["product_url"])
                        old_price = p["current_price"]
                        save_product(snapshot)

                        has_drop = (
                            old_price is not None
                            and snapshot.price is not None
                            and snapshot.price < old_price
                        )

                        entry = {
                            "product_id": snapshot.product_id,
                            "name": snapshot.name,
                            "old_price": old_price,
                            "new_price": snapshot.price,
                            "has_drop": has_drop,
                        }

                        updated.append(entry)
                        if has_drop:
                            drops.append(entry)

                    except Exception as exc:
                        errors.append(
                            {"product_id": p["product_id"], "error": str(exc)}
                        )

                self._send(
                    200,
                    {
                        "updated": updated,
                        "drops": drops,
                        "errors": errors,
                    },
                )
            except Exception as exc:
                self._send(500, {"error": str(exc)})
            return

        if parsed.path == "/remove":
            product_id = (params.get("product_id") or [""])[0].strip()
            if not product_id:
                self._send(400, {"error": "missing ?product_id="})
                return
            try:
                remove_product(product_id)
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
                self._send(200, {"history": get_price_history(product_id)})
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

    def _send(self, status, data):
        body = json.dumps(data, default=self._json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    init_db()
    print(f"Running at http://localhost:8000 using PostgreSQL database '{DB_NAME}'")
    HTTPServer(("localhost", 8000), Handler).serve_forever()
