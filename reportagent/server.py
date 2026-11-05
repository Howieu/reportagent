"""FastAPI 服务：工作台页面、会话、对话流和报告。默认只监听本机，没有账号体系。"""

import json
import os
import random
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

from .chat import ChatAgent
from .funnel import analyze_funnel
from .render import html_to_pdf_bytes, render_funnel
from .service import App
from .warehouse import DataUnavailable

STATIC = Path(__file__).parent / "static"
COOKIE = "ra_uid"
REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src https: http:; form-action 'self'"
class RateLimiter:
    """按访客的滑动窗口限流，保护模型额度。ponytail: 单进程内存计数；多实例时换 Redis。"""

    def __init__(self, limit, window=3600):
        self.limit, self.window, self.hits = limit, window, defaultdict(deque)

    def allow(self, key):
        now, q = time.time(), self.hits[key]
        while q and q[0] < now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


class ChatIn(BaseModel):
    message: str
    conversation: str | None = None
    assist: bool = False


class ReportIn(BaseModel):
    store: str
    category: str
    week: str | None = None
    channel: str | None = None
    focus: str | None = None


class TitleIn(BaseModel):
    title: str


def client_ip(request):
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def _json(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value))


def sse(event):
    return f"data: {json.dumps(event, ensure_ascii=False, default=_json)}\n\n"


def create_app(core: App | None = None) -> FastAPI:
    core = core or App()
    agent = ChatAgent(core)
    store = core.state
    secure = os.environ.get("REPORTAGENT_COOKIE_SECURE", "") == "1"
    chat_limit = RateLimiter(int(os.environ.get("REPORTAGENT_CHAT_PER_HOUR", "30")))
    report_limit = RateLimiter(int(os.environ.get("REPORTAGENT_REPORTS_PER_HOUR", "30")))
    api = FastAPI(title="ReportAgent", docs_url=None, redoc_url=None)

    @api.middleware("http")
    async def visitor_cookie(request: Request, call_next):
        uid = request.cookies.get(COOKIE) or secrets.token_urlsafe(16)
        request.state.uid = uid
        response = await call_next(request)
        if request.cookies.get(COOKIE) != uid:
            response.set_cookie(COOKIE, uid, max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax", secure=secure)
        return response

    @api.get("/healthz")
    def healthz():
        return {"ok": True}

    @api.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    @api.get("/api/meta")
    def meta():
        wh = core.wh
        stores = wh.stores()
        try:
            week = wh.latest_complete_week()
            latest = str(wh.latest_date())
        except Exception:
            week, latest = "", ""
        return {
            "name": core.semantic.name, "synthetic": core.semantic.synthetic, "branding": core.semantic.branding, "labels": core.semantic.labels, "llm": bool(core.llm and core.llm.enabled),
            "model": core.llm.model if core.llm and core.llm.enabled else None,
            "stores": [{"id": r["store"], "name": r["name"]} for _, r in stores.iterrows()],
            "categories": agent.tools.values("category"), "channels": agent.tools.values("channel"),
            "default_channel": core.semantic.default_channel, "default_focus": core.semantic.default_focus,
            "week": week, "latest": latest, "examples": random.sample(list(core.semantic.examples), len(core.semantic.examples)), "data_note": core.semantic.data_note, "has_funnel": core.semantic.has("funnel"),
        }

    @api.get("/api/conversations")
    def conversations(request: Request):
        return store.conversations(request.state.uid)

    @api.get("/api/conversations/{cid}")
    def conversation(cid: str, request: Request):
        data = store.conversation(cid, request.state.uid)
        if not data:
            raise HTTPException(404, "会话不存在")
        return data

    @api.patch("/api/conversations/{cid}")
    def rename(cid: str, body: TitleIn, request: Request):
        store.rename(cid, body.title.strip() or "新会话", request.state.uid)
        return {"ok": True}

    @api.delete("/api/conversations/{cid}")
    def delete(cid: str, request: Request):
        store.delete(cid, request.state.uid)
        return {"ok": True}

    @api.post("/api/chat")
    def chat(body: ChatIn, request: Request):
        question = body.message.strip()
        if not question or len(question) > 2000:
            raise HTTPException(400, "问题不能为空，也不能超过 2000 字")
        uid = request.state.uid
        if not chat_limit.allow(uid) or not chat_limit.allow(client_ip(request)):
            raise HTTPException(429, "提问太频繁，请稍后再试")
        cid = body.conversation if body.conversation and store.conversation(body.conversation, uid) else store.create(question, uid)
        history = store.conversation(cid, uid)["messages"]
        store.add(cid, "user", question)

        def stream():
            blocks, answer, finished = [], "", False
            try:
                yield sse({"type": "conversation", "id": cid})
                for event in agent.run(question, history, body.assist):
                    if event["type"] == "answer":
                        answer = event["text"]
                    elif event["type"] == "error":
                        answer = event["message"]
                    blocks.append(event)
                    yield sse(event)
                finished = True
                yield sse({"type": "end"})
            finally:
                if not finished:
                    blocks.append({"type": "stopped"})
                    answer = answer or "任务已终止"
                store.add(cid, "assistant", answer, json.loads(json.dumps(blocks, default=_json)))

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @api.post("/api/reports")
    def create_report(body: ReportIn, request: Request):
        if not report_limit.allow(request.state.uid) or not report_limit.allow(client_ip(request)):
            raise HTTPException(429, "生成报告太频繁，请稍后再试")
        try:
            meta_, _, _ = core.report(body.store, body.category, body.week or None, body.channel or None, body.focus or None)
        except (DataUnavailable, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return meta_

    def _funnel(request: Request):
        params = dict(request.query_params)
        week, dimension = params.pop("week", None), params.pop("dimension", None)
        try:
            return analyze_funnel(core.wh, week, dimension, params)
        except (DataUnavailable, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @api.get("/funnel", response_class=HTMLResponse)
    def funnel(request: Request):
        return HTMLResponse(render_funnel(_funnel(request)), headers={"Content-Security-Policy": REPORT_CSP})

    @api.get("/funnel/pdf")
    def funnel_pdf(request: Request):
        try:
            data = html_to_pdf_bytes(render_funnel(_funnel(request)))
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        return Response(data, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="funnel.pdf"'})

    @api.get("/reports/{report_id}", response_class=HTMLResponse)
    def report_html(report_id: str):
        html_text = core.report_html(report_id)
        if html_text is None:
            raise HTTPException(404, "报告不存在")
        return HTMLResponse(html_text, headers={"Content-Security-Policy": REPORT_CSP})

    @api.get("/reports/{report_id}/pdf")
    def report_pdf(report_id: str):
        try:
            data = core.pdf(report_id)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        if data is None:
            raise HTTPException(404, "报告不存在")
        return Response(data, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="report.pdf"'})

    return api
