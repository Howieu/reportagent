"""把本地 DuckDB 数仓导入 Postgres（Supabase），并建最小权限账号。

数据放在 warehouse schema，应用状态放在 app schema，都不在 Supabase API 暴露的 public 里。
"""

import duckdb
import psycopg
from psycopg import sql as psql

TYPES = {"DATE": "date", "VARCHAR": "text", "BOOLEAN": "boolean", "BIGINT": "bigint", "INTEGER": "integer", "DOUBLE": "double precision"}
TABLES = {"dim_store": None, "dim_item": None, "fact_sales": None, "fact_funnel": "biz_date >= DATE '{since}'"}
INDEXES = [
    "CREATE INDEX ON warehouse.fact_sales (biz_date, store_id, category)",
    "CREATE INDEX ON warehouse.fact_funnel (biz_date, event)",
    "CREATE INDEX ON warehouse.dim_item (item_id)",
]


def _pg_type(duck_type):
    if duck_type.startswith("DECIMAL"):
        return "numeric"
    return TYPES[duck_type]


def push(duck_path, admin_url, funnel_since="2015-06-29"):
    src = duckdb.connect(str(duck_path), read_only=True)
    with psycopg.connect(admin_url, autocommit=True) as pg:
        pg.execute("SET statement_timeout = 0")
        pg.execute("CREATE SCHEMA IF NOT EXISTS warehouse")
        for name, where in TABLES.items():
            columns = src.execute(f"DESCRIBE warehouse.{name}").fetchall()
            ddl = ", ".join(f'"{c[0]}" {_pg_type(c[1])}' for c in columns)
            pg.execute(f"DROP TABLE IF EXISTS warehouse.{name}")
            pg.execute(f"CREATE TABLE warehouse.{name} ({ddl})")
            sql = f"SELECT * FROM warehouse.{name}" + (f" WHERE {where.format(since=funnel_since)}" if where else "")
            cursor = src.execute(sql)
            total = 0
            with pg.cursor() as cur, cur.copy(f"COPY warehouse.{name} FROM STDIN") as copy:
                while batch := cursor.fetchmany(50000):
                    for row in batch:
                        copy.write_row(row)
                    total += len(batch)
            print(name, total, flush=True)
        for index in INDEXES:
            pg.execute(index)
        pg.execute("ANALYZE")
        size = pg.execute("SELECT pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
        print("database size", size)


def create_roles(admin_url, ro_password, app_password):
    with psycopg.connect(admin_url, autocommit=True) as pg:
        pg.execute("CREATE SCHEMA IF NOT EXISTS app")
        for role, password in (("reportagent_ro", ro_password), ("reportagent_app", app_password)):
            exists = pg.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
            verb = "ALTER" if exists else "CREATE"
            pg.execute(f"{verb} ROLE {role} WITH LOGIN PASSWORD {psql.Literal(password).as_string(pg)}")
        pg.execute("GRANT USAGE ON SCHEMA warehouse TO reportagent_ro")
        pg.execute("GRANT SELECT ON ALL TABLES IN SCHEMA warehouse TO reportagent_ro")
        pg.execute("ALTER ROLE reportagent_ro SET default_transaction_read_only = on")
        pg.execute("ALTER ROLE reportagent_ro SET statement_timeout = '60s'")
        pg.execute("GRANT USAGE, CREATE ON SCHEMA app TO reportagent_app")
        pg.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL ON TABLES TO reportagent_app")
        pg.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL ON SEQUENCES TO reportagent_app")
