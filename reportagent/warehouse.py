"""数仓访问层：所有 SQL 都在这里由代码生成，LLM 无法写入任意 SQL。

一条查询用条件聚合同时算出多个时间段，方言差异交给 SQLAlchemy。
"""

import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import and_, case, column, create_engine, distinct, func, or_, select, table

from .config import Semantic


class DataUnavailable(Exception):
    """数据不足以回答：提示给用户，而不是产出残缺结果。"""


@dataclass(frozen=True)
class Period:
    start: date
    end: date


def parse_week(week) -> date:
    """YYYYWW（ISO 周）→ 周一。"""
    text = str(week)
    if len(text) != 6 or not text.isdigit():
        raise ValueError(f"周次格式应为 YYYYWW，例如 202644，收到: {week}")
    try:
        return date.fromisocalendar(int(text[:4]), int(text[4:]), 1)
    except ValueError as exc:
        raise ValueError(f"无效周次: {week}") from exc


def week_of(day: date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}{w:02d}"


def fiscal_start(day: date, month: int) -> date:
    return date(day.year if day.month >= month else day.year - 1, month, 1)


def build_periods(week, semantic: Semantic, trend_weeks=4) -> dict:
    """本周 / 滚动 4 周 / 财年累计 + 各自去年同期 + 近 N 周趋势。"""
    start = parse_week(week)
    end = start + timedelta(days=6)
    base = {
        "week": Period(start, end),
        "r4": Period(start - timedelta(days=21), end),
        "ytd": Period(fiscal_start(end, semantic.fiscal_year_start_month), end),
    }
    for i in range(1, trend_weeks):
        s = start - timedelta(days=7 * i)
        base[f"w{i}"] = Period(s, s + timedelta(days=6))
    shift = timedelta(days=semantic.ly_shift_days)
    periods = dict(base)
    for key, p in base.items():
        periods[f"{key}_ly"] = Period(p.start - shift, p.end - shift)
    return periods


def _merged(periods):
    merged = []
    for p in sorted(periods, key=lambda x: x.start):
        if merged and p.start <= merged[-1].end + timedelta(days=1):
            merged[-1] = Period(merged[-1].start, max(merged[-1].end, p.end))
        else:
            merged.append(p)
    return merged


class Warehouse:
    def __init__(self, semantic: Semantic, url=None, engine=None):
        self.semantic = semantic
        self.url = url or os.environ.get("REPORTAGENT_DB_URL")
        if engine is None:
            if not self.url:
                raise ValueError("未配置 REPORTAGENT_DB_URL")
            kwargs = {}
            if self.url.startswith("duckdb"):
                kwargs["connect_args"] = {"read_only": True}
            engine = create_engine(self.url, **kwargs)
        self.engine = engine
        self.log = []

    def _bind(self, day: date):
        fmt = self.semantic.date_format
        return day.strftime(fmt) if fmt else day

    def _table(self, source, names):
        src = self.semantic.source(source)
        parts = src.table.split(".")
        cols = sorted({src.col(n) if n in src.columns else n for n in names})
        return table(parts[-1], *[column(c) for c in cols], schema=".".join(parts[:-1]) or None)

    def statement(self, source, dims, measures, periods, filters=None):
        src = self.semantic.source(source)
        filters = filters or {}
        names = [*dims, *filters, "date", *[m[1] for m in measures.values()]]
        tbl = self._table(source, names)
        date_col = tbl.c[src.col("date")]
        selects = [tbl.c[src.col(d)].label(d) for d in dims]
        for name, (kind, logical) in measures.items():
            col = tbl.c[src.col(logical)]
            for key, p in periods.items():
                cond = and_(date_col >= self._bind(p.start), date_col <= self._bind(p.end))
                value = case((cond, col))
                expr = {"sum": func.sum, "avg": func.avg}[kind](value) if kind != "distinct" \
                    else func.count(distinct(value))
                selects.append(expr.label(f"{name}__{key}"))
        where = [or_(*[and_(date_col >= self._bind(p.start), date_col <= self._bind(p.end))
                       for p in _merged(periods.values())])]
        for key, value in filters.items():
            col = tbl.c[src.col(key)]
            where.append(col.in_(value) if isinstance(value, (list, tuple, set)) else col == value)
        stmt = select(*selects).where(*where)
        return stmt.group_by(*[tbl.c[src.col(d)] for d in dims]) if dims else stmt

    def run(self, stmt, purpose=""):
        started = time.perf_counter()
        with self.engine.connect() as conn:
            df = pd.read_sql(stmt, conn)
        self.log.append({
            "purpose": purpose,
            "sql": self.sql_text(stmt),
            "rows": len(df),
            "ms": round((time.perf_counter() - started) * 1000),
        })
        return df

    def sql_text(self, stmt):
        return str(stmt.compile(self.engine, compile_kwargs={"literal_binds": True}))

    def aggregate(self, source, dims, measures, periods, filters=None, purpose=""):
        df = self.run(self.statement(source, dims, measures, periods, filters), purpose)
        for col in df.columns:
            if col in dims:
                df[col] = df[col].astype(str)
            else:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        return df

    def sales(self, dims, periods, filters=None, purpose="", tickets=True):
        measures = {"sales": ("sum", "sales"), "qty": ("sum", "qty")}
        if tickets:
            measures["tickets"] = ("distinct", "ticket")
        return self.aggregate("sales", dims, measures, periods, filters, purpose)

    def latest_date(self, source="sales"):
        src = self.semantic.source(source)
        tbl = self._table(source, ["date"])
        stmt = select(func.max(tbl.c[src.col("date")]).label("d"))
        value = self.run(stmt, "最新数据日期").iloc[0]["d"]
        if value is None or pd.isna(value):
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        fmt = self.semantic.date_format
        return datetime.strptime(str(value), fmt).date() if fmt else pd.to_datetime(value).date()

    def latest_complete_week(self):
        latest = self.latest_date()
        if latest is None:
            raise DataUnavailable("销售表没有数据")
        if latest.isoweekday() != 7:
            latest -= timedelta(days=latest.isoweekday())
        return week_of(latest)

    def distinct_values(self, source, logical):
        src = self.semantic.source(source)
        tbl = self._table(source, [logical])
        col = tbl.c[src.col(logical)]
        stmt = select(col.label("v")).distinct().order_by(col).limit(2000)
        return [str(v) for v in self.run(stmt, f"{logical} 取值")["v"].dropna()]

    def stores(self):
        """门店维度；没配 stores 表时从销售表取，全部视为同一对标组。"""
        if self.semantic.has("stores"):
            src = self.semantic.source("stores")
            names = [n for n in ("store", "name", "peer_group", "region", "city") if src.has(n)]
            tbl = self._table("stores", names)
            df = self.run(select(*[tbl.c[src.col(n)].label(n) for n in names]), "门店维度").astype(str)
        else:
            df = pd.DataFrame({"store": self.distinct_values("sales", "store")})
        for col, default in (("name", None), ("peer_group", "ALL"), ("region", ""), ("city", "")):
            if col not in df:
                df[col] = df["store"] if col == "name" else default
        return df

    def items(self, ids):
        """按 ID 取商品属性，分批避免超长 IN。"""
        cols = ["item", "name", "image_url", "exclude", *[f"seg:{s}" for s in self.semantic.sources.get(
            "items", _EMPTY).segments]]
        if not self.semantic.has("items") or not ids:
            return pd.DataFrame(columns=cols)
        src = self.semantic.source("items")
        names = ["item", *[n for n in ("name", "image_url", "exclude_flag") if src.has(n)]]
        tbl = self._table("items", [*names, *src.segments.values()])
        selects = [tbl.c[src.col(n)].label(n) for n in names]
        selects += [tbl.c[c].label(f"seg:{s}") for s, c in src.segments.items()]
        frames = []
        ids = list(ids)
        for i in range(0, len(ids), 500):
            stmt = select(*selects).where(tbl.c[src.col("item")].in_(ids[i:i + 500]))
            frames.append(self.run(stmt, "商品属性"))
        df = pd.concat(frames).rename(columns={"exclude_flag": "exclude"})
        df["item"] = df["item"].astype(str)
        return df

    def check(self):
        """逐表校验配置的字段是否存在，返回 [(来源, 表, 问题或 None)]。"""
        results = []
        for name, src in self.semantic.sources.items():
            fields = [c for c in src.columns.values()] + list(src.segments.values())
            parts = src.table.split(".")
            tbl = table(parts[-1], *[column(c) for c in sorted(set(fields))],
                        schema=".".join(parts[:-1]) or None)
            try:
                with self.engine.connect() as conn:
                    conn.execute(select(*tbl.c).limit(1)).close()
                results.append((name, src.table, None))
            except Exception as exc:
                results.append((name, src.table, str(exc).splitlines()[0][:200]))
        return results


class _Empty:
    segments = {}


_EMPTY = _Empty()
