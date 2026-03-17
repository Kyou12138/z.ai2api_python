"""Vercel FastAPI 入口。"""

from main import app as application

app = application

__all__ = ["app"]
