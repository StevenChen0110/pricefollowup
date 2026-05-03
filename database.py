import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "pricewise.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    url         TEXT    UNIQUE,
    platform    TEXT    DEFAULT 'momo',
    image_url   TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    price       REAL    NOT NULL,
    in_stock    BOOLEAN DEFAULT 1,
    scraped_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_groups (
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    group_id    INTEGER NOT NULL REFERENCES groups(id)   ON DELETE CASCADE,
    PRIMARY KEY (product_id, group_id)
);

CREATE INDEX IF NOT EXISTS idx_price_history_product ON price_history(product_id);
CREATE INDEX IF NOT EXISTS idx_price_history_scraped ON price_history(scraped_at);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ── Products ──────────────────────────────────────────────────────────────────

def upsert_product(name: str, url: str, platform: str = "momo", image_url: str = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO products (name, url, platform, image_url)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET
                   name      = excluded.name,
                   image_url = excluded.image_url,
                   updated_at = CURRENT_TIMESTAMP
               RETURNING id""",
            (name, url, platform, image_url),
        )
        return cur.fetchone()[0]


def get_all_products():
    with get_conn() as conn:
        return conn.execute("""
            SELECT p.*,
                   ph.price      AS latest_price,
                   ph.scraped_at AS last_checked
            FROM products p
            LEFT JOIN price_history ph ON ph.id = (
                SELECT id FROM price_history
                WHERE product_id = p.id
                ORDER BY scraped_at DESC LIMIT 1
            )
            ORDER BY p.updated_at DESC
        """).fetchall()


def get_product(product_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()


def delete_product(product_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))


# ── Price History ─────────────────────────────────────────────────────────────

def add_price(product_id: int, price: float, in_stock: bool = True):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO price_history (product_id, price, in_stock) VALUES (?, ?, ?)",
            (product_id, price, in_stock),
        )
        conn.execute(
            "UPDATE products SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (product_id,),
        )


def get_price_history(product_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT price, in_stock, scraped_at FROM price_history "
            "WHERE product_id = ? ORDER BY scraped_at ASC",
            (product_id,),
        ).fetchall()


def get_price_stats(product_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                AVG(price)  AS avg_price,
                MIN(price)  AS min_price,
                MAX(price)  AS max_price,
                COUNT(*)    AS data_points
            FROM price_history WHERE product_id = ?
        """, (product_id,)).fetchone()
        return dict(row) if row else {}


# ── Groups ────────────────────────────────────────────────────────────────────

def get_all_groups():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM groups ORDER BY name").fetchall()


def create_group(name: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO groups (name) VALUES (?) RETURNING id", (name,)
        )
        row = cur.fetchone()
        if row:
            return row[0]
        return conn.execute("SELECT id FROM groups WHERE name = ?", (name,)).fetchone()[0]


def assign_group(product_id: int, group_id: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO product_groups VALUES (?, ?)",
            (product_id, group_id),
        )


def remove_group(product_id: int, group_id: int):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM product_groups WHERE product_id = ? AND group_id = ?",
            (product_id, group_id),
        )


def get_products_in_group(group_id: int):
    with get_conn() as conn:
        return conn.execute("""
            SELECT p.*,
                   ph.price      AS latest_price,
                   ph.scraped_at AS last_checked
            FROM products p
            JOIN product_groups pg ON pg.product_id = p.id
            LEFT JOIN price_history ph ON ph.id = (
                SELECT id FROM price_history
                WHERE product_id = p.id
                ORDER BY scraped_at DESC LIMIT 1
            )
            WHERE pg.group_id = ?
        """, (group_id,)).fetchall()


def get_product_groups(product_id: int):
    with get_conn() as conn:
        return conn.execute("""
            SELECT g.* FROM groups g
            JOIN product_groups pg ON pg.group_id = g.id
            WHERE pg.product_id = ?
        """, (product_id,)).fetchall()


# ── AI context ────────────────────────────────────────────────────────────────

def get_ai_context_summary() -> str:
    """Return a compact text summary of the DB for use as LLM context."""
    with get_conn() as conn:
        products = conn.execute("""
            SELECT p.name, p.platform, p.url,
                   ph.price AS latest_price, ph.scraped_at,
                   stats.avg_price, stats.min_price, stats.max_price
            FROM products p
            LEFT JOIN price_history ph ON ph.id = (
                SELECT id FROM price_history WHERE product_id = p.id
                ORDER BY scraped_at DESC LIMIT 1
            )
            LEFT JOIN (
                SELECT product_id,
                       ROUND(AVG(price), 0) AS avg_price,
                       MIN(price) AS min_price,
                       MAX(price) AS max_price
                FROM price_history GROUP BY product_id
            ) stats ON stats.product_id = p.id
        """).fetchall()

    lines = ["# PriceWise 追蹤商品摘要\n"]
    for p in products:
        lines.append(
            f"- **{p['name']}** ({p['platform']}): "
            f"最新 ${p['latest_price']}, 均價 ${p['avg_price']}, "
            f"最低 ${p['min_price']}, 最高 ${p['max_price']}, "
            f"最後更新 {p['scraped_at']}"
        )
    return "\n".join(lines)
