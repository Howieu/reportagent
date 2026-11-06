"""Vercel 入口：FastAPI 应用，同时提供页面和接口。"""

from reportagent.server import create_app

app = create_app()
