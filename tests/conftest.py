import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from reportagent.config import load_semantic
from reportagent.demo import TARGET_WEEK, build
from reportagent.service import App, State

YAML = """
name: 手算小数仓
calendar: {fiscal_year_start_month: 1, ly_shift_days: 364}
defaults: {channel: RETAIL, focus: sales}
sources:
  sales: {table: s, date: d, store: st, channel: ch, category: cat, subcategory: sub, family: fam, item: it,
          sales: amt, qty: q, ticket: t}
"""


@pytest.fixture(scope="session")
def demo_app(tmp_path_factory):
    path = tmp_path_factory.mktemp("wh") / "demo.duckdb"
    build(str(path), tickets_per_day=12)
    state = State(f"sqlite:///{path.parent / 'app.db'}")
    return App("semantic.demo.yaml", url=f"duckdb:///{path}", llm=False, state=state)


@pytest.fixture(scope="session")
def week():
    return TARGET_WEEK


@pytest.fixture()
def tiny(tmp_path):
    """SQLite 手算数据：验证 SQL 结果，也验证非 DuckDB 方言能跑。"""
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    # 202644 = 2026-10-26..11-01；LY = 2025-10-27..11-02
    rows = [
        ("2026-10-26", "A", "RETAIL", "X", "x1", "F1", "i1", 300, 3, "t1"),
        ("2026-10-27", "A", "RETAIL", "X", "x1", "F1", "i1", 100, 1, "t1"),
        ("2026-10-27", "A", "RETAIL", "X", "x1", "F2", "i2", 100, 1, "t2"),
        ("2025-10-27", "A", "RETAIL", "X", "x1", "F1", "i1", 200, 2, "l1"),
        ("2025-10-28", "A", "RETAIL", "X", "x1", "F2", "i2", 300, 3, "l2"),
        ("2026-10-26", "B", "RETAIL", "X", "x1", "F1", "i1", 900, 9, "t3"),
        ("2025-10-27", "B", "RETAIL", "X", "x1", "F1", "i1", 600, 6, "l3"),
        ("2026-11-01", "A", "ONLINE", "X", "x1", "F1", "i1", 50, 1, "t4"),
        ("2025-11-02", "A", "ONLINE", "X", "x1", "F1", "i1", 100, 1, "l4"),
        ("2026-10-19", "A", "RETAIL", "X", "x1", "F1", "i1", 999, 9, "old"),
    ]
    with engine.begin() as c:
        c.execute(text("CREATE TABLE s (d TEXT, st TEXT, ch TEXT, cat TEXT, sub TEXT, fam TEXT, it TEXT, amt REAL, q INT, t TEXT)"))
        c.execute(text("INSERT INTO s VALUES (:a,:b,:c,:d,:e,:f,:g,:h,:i,:j)"),
                  [dict(zip("abcdefghij", r)) for r in rows])
    path = tmp_path / "s.yaml"
    path.write_text(YAML + '\nlabels: {}\n', encoding="utf-8")
    sem = path
    text_cfg = path.read_text(encoding="utf-8").replace("calendar: {", 'calendar: {date_format: "%Y-%m-%d", ')
    path.write_text(text_cfg, encoding="utf-8")
    assert load_semantic(sem).date_format
    return App(str(sem), engine=engine, llm=False, state=State(f"sqlite:///{tmp_path / 'app.db'}"))
