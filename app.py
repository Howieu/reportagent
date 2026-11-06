"""Vercel 入口：FastAPI 应用。页面由 public/ 提供。"""

from reportagent.server import create_app

app = create_app()
