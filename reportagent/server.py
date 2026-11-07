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
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .chat import ChatAgent
from .funnel import analyze_funnel
from .render import find_chrome, html_to_pdf_bytes, render_funnel
from .service import App
from .tools import web_search_enabled
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
    project: str | None = None
    assist: bool = False
    web: bool = False


class ReportIn(BaseModel):
    store: str
    category: str
    week: str | None = None
    channel: str | None = None
    focus: str | None = None
    project: str | None = None


class TitleIn(BaseModel):
    title: str | None = None
    project: str | None = None
    move: bool = False


class ProjectIn(BaseModel):
    name: str


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
    web_limit = RateLimiter(int(os.environ.get("REPORTAGENT_WEB_PER_HOUR", "10")))
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
        page = STATIC / "index.html"
        if not page.exists():
            raise HTTPException(404, "前端没有构建。线上前端在 Vercel；本地请运行 cd web && npm run build")
        # 首页不带 ETag：部署后文件时间不变时，校验缓存可能让老用户拿到引用旧资源的页面而白屏
        return HTMLResponse(page.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})

    if (STATIC / "assets").exists():
        api.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

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
            "agents_ready": bool(core.llm and core.llm.enabled),
            "stores": [{"id": r["store"], "name": r["name"]} for _, r in stores.iterrows()],
            "categories": agent.tools.values("category"), "channels": agent.tools.values("channel"),
            "default_channel": core.semantic.default_channel, "default_focus": core.semantic.default_focus, "default_category": core.semantic.default_category,
            "week": week, "latest": latest, "examples": random.sample(list(core.semantic.examples), len(core.semantic.examples)), "data_note": core.semantic.data_note, "has_funnel": core.semantic.has("funnel"), "server_pdf": bool(find_chrome()), "web_search": web_search_enabled(),
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
        if body.title is not None:
            store.rename(cid, body.title.strip() or "新任务", request.state.uid)
        if body.move:
            store.move(cid, body.project, request.state.uid)
        return {"ok": True}

    @api.get("/api/projects")
    def projects(request: Request):
        return store.projects(request.state.uid)

    @api.post("/api/projects")
    def create_project(body: ProjectIn, request: Request):
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "项目名称不能为空")
        return store.create_project(name, request.state.uid)

    @api.patch("/api/projects/{pid}")
    def rename_project(pid: str, body: ProjectIn, request: Request):
        store.rename_project(pid, body.name.strip() or "未命名项目", request.state.uid)
        return {"ok": True}

    @api.delete("/api/projects/{pid}")
    def delete_project(pid: str, request: Request):
        store.delete_project(pid, request.state.uid)
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
        cid = body.conversation if body.conversation and store.conversation(body.conversation, uid) else store.create(question, uid, body.project)
        history = store.conversation(cid, uid)["messages"]
        web = body.web and web_search_enabled()
        web_blocked = web and not (web_limit.allow(uid) and web_limit.allow(client_ip(request)))
        web = web and not web_blocked
        store.add(cid, "user", question)

        def stream():
            blocks, answer, finished = [], "", False
            try:
                yield sse({"type": "conversation", "id": cid})
                if web_blocked:
                    yield sse({"type": "notice", "text": "联网搜索已达每小时上限，这次不联网。"})
                for event in agent.run(question, history, body.assist, web):
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
            meta_, _, sections = core.report(body.store, body.category, body.week or None, body.channel or None, body.focus or None)
        except (DataUnavailable, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        # 直接生成的报告也是一个任务，才能归到项目里、之后接着追问
        cid = store.create(meta_["title"], request.state.uid, body.project)
        store.add(cid, "user", f"生成报告：{meta_['title']}")
        summary = sections["summary"]["text"]
        store.add(cid, "assistant", summary, [{"type": "answer", "text": summary, "mode": "model", "suggestions": []},
                                              {"type": "result", "kind": "report", "report": meta_, "assumptions": []}])
        return {**meta_, "conversation": cid}

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

    def _forecast_html(request: Request):
        if not report_limit.allow(request.state.uid) or not report_limit.allow(client_ip(request)):
            raise HTTPException(429, "预测太频繁，请稍后再试")
        q = request.query_params
        try:
            return core.forecast_html(q.get("store") or None, q.get("category") or None, q.get("metric") or "sales", q.get("week") or None,
                                      lever=q.get("lever") or None, change=q.get("change") or None)
        except (DataUnavailable, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @api.get("/forecast", response_class=HTMLResponse)
    def forecast_page(request: Request):
        return HTMLResponse(_forecast_html(request), headers={"Content-Security-Policy": REPORT_CSP})

    @api.get("/forecast/pdf")
    def forecast_pdf(request: Request):
        try:
            data = html_to_pdf_bytes(_forecast_html(request))
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        return Response(data, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="forecast.pdf"'})

    def _checkup_html(request: Request):
        if not report_limit.allow(request.state.uid) or not report_limit.allow(client_ip(request)):
            raise HTTPException(429, "体检太频繁，请稍后再试")
        q = request.query_params
        try:
            return core.checkup_html(q.get("store") or None, q.get("category") or None, q.get("metric") or "sales", q.get("week") or None)
        except (DataUnavailable, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @api.get("/checkup", response_class=HTMLResponse)
    def checkup_page(request: Request):
        return HTMLResponse(_checkup_html(request), headers={"Content-Security-Policy": REPORT_CSP})

    @api.get("/checkup/pdf")
    def checkup_pdf(request: Request):
        try:
            data = html_to_pdf_bytes(_checkup_html(request))
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        return Response(data, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="checkup.pdf"'})

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
