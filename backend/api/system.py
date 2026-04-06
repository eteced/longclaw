"""
System API for LongClaw.
Provides system control endpoints like restart.
"""
import logging
import signal
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class RestartResponse(BaseModel):
    """Response for restart endpoint."""

    status: str
    message: str


@router.post("/restart", response_model=RestartResponse)
async def restart_backend() -> RestartResponse:
    """Restart the backend service.

    This endpoint triggers a graceful shutdown and restart of the uvicorn server.

    Returns:
        Restart response.

    Raises:
        HTTPException: If restart fails.
    """
    import os
    import sys

    logger.info("Restart requested via API")

    # Find all uvicorn processes
    try:
        result = subprocess.run(
            ["pgrep", "-f", "uvicorn.*backend.main:app"],
            capture_output=True,
            text=True
        )

        pids = []
        if result.stdout.strip():
            pids = [int(p) for p in result.stdout.strip().split("\n")]
            logger.info(f"Found uvicorn processes: {pids}")

            # Kill all uvicorn processes
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)  # Use SIGKILL to ensure termination
                    logger.info(f"Killed uvicorn process {pid}")
                except OSError as e:
                    logger.warning(f"Failed to kill process {pid}: {e}")

        # Schedule restart after a short delay
        def delayed_restart():
            import time
            time.sleep(2)
            subprocess.Popen(
                [
                    "bash", "-c",
                    "cd /root/longclaw && "
                    "PYTHONPATH=/root/longclaw nohup "
                    "/root/longclaw/backend/venv/bin/python -m uvicorn "
                    "backend.main:app --host 0.0.0.0 --port 8001 >> /tmp/backend.log 2>&1 &"
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.info("Restart scheduled")

        import threading
        thread = threading.Thread(target=delayed_restart)
        thread.daemon = True
        thread.start()

        return RestartResponse(
            status="restarting",
            message=f"Backend restart initiated. {len(pids)} process(es) killed."
        )
    except Exception as e:
        logger.error(f"Restart failed: {e}")
        raise HTTPException(status_code=500, detail=f"Restart failed: {str(e)}")


@router.get("/status", response_model=dict)
async def get_system_status() -> dict:
    """Get system status.

    Returns:
        System status information.
    """
    import os
    import subprocess
    import sys

    status = {
        "python_version": sys.version,
        "pid": os.getpid(),
    }

    # Check uvicorn process
    try:
        result = subprocess.run(
            ["pgrep", "-f", "uvicorn.*backend.main:app"],
            capture_output=True,
            text=True
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            status["uvicorn_pids"] = pids
            status["uvicorn_running"] = True
        else:
            status["uvicorn_running"] = False
    except Exception:
        status["uvicorn_running"] = False

    return status
