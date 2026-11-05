"""CLI、Web、对话共用的装配入口。"""

import json
import os
import secrets
import time
from pathlib import Path

from sqlalchemy import create_engine, text

from .analysis import analyze
from .config import load_env, load_semantic
from .narrative import CURRENCY, LLM, write_sections
from .render import html_to_pdf_bytes, render_html
from .warehouse import Warehouse

DATA_DIR = Path(os.environ.get("REPORTAGENT_DATA", "data"))



class State:
    """会话和报告存储。本地默认 SQLite，线上指向 Supabase 的 app schema。

    ponytail: 没有账号体系，靠随机 cookie 隔离访客；要多人协作或长期保存时再接登录。
    """

    def __init__(self, url=None):
        self.url = url or os.environ.get("REPORTAGENT_APP_DB_URL") or f"sqlite:///{DATA_DIR / 'app.db'}"
        if self.url.startswith("sqlite"):
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.prefix = "app." if self.url.startswith("postgresql") else ""
        self.engine = create_engine(self.url, pool_pre_ping=True)
        p = self.prefix
        with self.engine.begin() as db:
            if p:
                db.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
            db.execute(text(f"CREATE TABLE IF NOT EXISTS {p}conversations (id TEXT PRIMARY KEY, owner TEXT, title TEXT, created DOUBLE PRECISION, updated DOUBLE PRECISION)"))
            serial = "BIGSERIAL PRIMARY KEY" if p else "INTEGER PRIMARY KEY AUTOINCREMENT"
            db.execute(text(f"CREATE TABLE IF NOT EXISTS {p}messages (id {serial}, conversation TEXT, role TEXT, content TEXT, blocks TEXT, created DOUBLE PRECISION)"))
            db.execute(text(f"CREATE TABLE IF NOT EXISTS {p}reports (id TEXT PRIMARY KEY, html TEXT, meta TEXT, created DOUBLE PRECISION)"))

    def _rows(self, sql, **params):
        with self.engine.connect() as db:
            return [dict(r._mapping) for r in db.execute(text(sql.replace("{p}", self.prefix)), params)]

    def _run(self, sql, **params):
        with self.engine.begin() as db:
            db.execute(text(sql.replace("{p}", self.prefix)), params)

    def conversations(self, owner):
        return self._rows("SELECT id, title, created, updated FROM {p}conversations WHERE owner=:o ORDER BY updated DESC", o=owner)

    def conversation(self, cid, owner):
        head = self._rows("SELECT id, title, created, updated FROM {p}conversations WHERE id=:i AND owner=:o", i=cid, o=owner)
        if not head:
            return None
        rows = self._rows("SELECT role, content, blocks FROM {p}messages WHERE conversation=:i ORDER BY id", i=cid)
        return {**head[0], "messages": [{"role": r["role"], "content": r["content"], "blocks": json.loads(r["blocks"] or "[]")} for r in rows]}

    def create(self, title, owner):
        cid, now = secrets.token_hex(8), time.time()
        self._run("INSERT INTO {p}conversations VALUES (:i,:o,:t,:n,:n)", i=cid, o=owner, t=title[:60], n=now)
        return cid

    def add(self, cid, role, content, blocks=()):
        now = time.time()
        self._run("INSERT INTO {p}messages (conversation, role, content, blocks, created) VALUES (:c,:r,:t,:b,:n)",
                  c=cid, r=role, t=content, b=json.dumps(list(blocks), ensure_ascii=False), n=now)
        self._run("UPDATE {p}conversations SET updated=:n WHERE id=:c", n=now, c=cid)

    def rename(self, cid, title, owner):
        self._run("UPDATE {p}conversations SET title=:t WHERE id=:i AND owner=:o", t=title[:60], i=cid, o=owner)

    def delete(self, cid, owner):
        if self.conversation(cid, owner):
            self._run("DELETE FROM {p}messages WHERE conversation=:i", i=cid)
            self._run("DELETE FROM {p}conversations WHERE id=:i", i=cid)

    def save_report(self, report_id, html_text, meta):
        self._run("INSERT INTO {p}reports VALUES (:i,:h,:m,:n)", i=report_id, h=html_text, m=json.dumps(meta, ensure_ascii=False), n=time.time())

    def report_html(self, report_id):
        rows = self._rows("SELECT html FROM {p}reports WHERE id=:i", i=report_id)
        return rows[0]["html"] if rows else None


class App:
    def __init__(self, semantic_path=None, url=None, llm=None, engine=None, state=None):
        load_env()
        path = semantic_path or os.environ.get("REPORTAGENT_SEMANTIC", "semantic.demo.yaml")
        self.semantic = load_semantic(path)
        CURRENCY["symbol"] = self.semantic.currency
        self.wh = Warehouse(self.semantic, url=url, engine=engine)
        self.llm = llm if llm is not None else LLM()
        self.state = state or State()

    def report(self, store, category, week=None, channel=None, focus=None, use_llm=True):
        """生成报告并保存，返回元数据、分析结果和文字段落。"""
        week = week or self.wh.latest_complete_week()
        del self.wh.log[:-500]
        start = len(self.wh.log)
        result = analyze(self.wh, store, category, week, channel, focus)
        sections = write_sections(result, self.semantic, self.llm if use_llm else None)
        html_text = render_html(result, sections, self.wh.log[start:])
        report_id = secrets.token_urlsafe(12)
        meta = {"id": report_id, "title": f"{result['store_name']} · {category} · wk{week}", "store": store,
                "category": category, "week": str(week), "channel": result["channel"], "focus": result["focus"],
                "modes": {k: v["mode"] for k, v in sections.items()}}
        self.state.save_report(report_id, html_text, meta)
        return meta, result, sections

    def report_html(self, report_id):
        return self.state.report_html(report_id)

    def pdf(self, report_id):
        html_text = self.report_html(report_id)
        return html_to_pdf_bytes(html_text) if html_text else None
