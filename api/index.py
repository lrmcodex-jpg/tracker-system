"""Vercel serverless entry point. Exposes the ASGI web app.

Vercel's Python runtime looks for an ASGI/WSGI `app` in files under /api.
This imports the Find-My-free web app so the bundle stays small.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.web import app  # noqa: E402

# Vercel uses `app` directly as the ASGI application.
