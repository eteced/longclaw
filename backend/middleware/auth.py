"""
Authentication middleware for LongClaw.
"""
import re
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send, Message

from backend.config import get_settings


class AuthMiddleware:
    """Middleware to check API key authentication."""

    # Paths that don't require authentication
    PUBLIC_PATHS = [
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/ws",  # WebSocket endpoint
    ]

    def __init__(self, app: ASGIApp) -> None:
        """Initialize the middleware.

        Args:
            app: The ASGI application.
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process the request.

        Args:
            scope: The ASGI scope.
            receive: The receive callable.
            send: The send callable.
        """
        # Only process HTTP requests, pass through WebSocket and other types
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Check if path is public
        if self._is_public_path(scope["path"]):
            await self.app(scope, receive, send)
            return

        # Get API key from header or cookie
        headers = dict(scope.get("headers", []))
        api_key = headers.get(b"x-api-key", b"").decode("utf-8")
        if not api_key:
            # Try cookie
            cookie_header = headers.get(b"cookie", b"").decode("utf-8")
            for cookie in cookie_header.split(";"):
                cookie = cookie.strip()
                if cookie.startswith("api_key="):
                    api_key = cookie[8:]
                    break

        # Validate API key
        settings = get_settings()
        if not api_key or api_key != settings.api_key:
            # Send 401 response
            response = Response(
                content='{"detail":"Unauthorized. Valid API key required."}',
                status_code=401,
                media_type="application/json",
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _is_public_path(self, path: str) -> bool:
        """Check if the path is public (doesn't require authentication).

        Args:
            path: The request path.

        Returns:
            True if the path is public.
        """
        # Exact match for public paths
        if path in self.PUBLIC_PATHS:
            return True

        # Allow static files and favicon
        if path.startswith("/static") or path == "/favicon.ico":
            return True

        return False
