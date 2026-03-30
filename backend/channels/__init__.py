"""
Channels package for LongClaw.
"""
from backend.channels.base_channel import BaseChannel
from backend.channels.web_channel import WebChannel

__all__ = ["BaseChannel", "WebChannel"]
