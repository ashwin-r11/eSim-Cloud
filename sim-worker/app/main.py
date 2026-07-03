"""
Sim-Worker: HTTP service entry-point.

Exposes a minimal FastAPI application so the Django backend (or the
session-manager) can POST a SPICE netlist and receive simulation results
via a JSON response.

Endpoints
---------
POST /simulate
    Body (multipart or JSON):
        netlist  – raw SPICE netlist text
        job_id   – (optional) opaque identifier echoed back in response
        timeout  – (optional) max execution seconds (default 300)

GET  /health
    Always returns {"status": "healthy"}
"""
import json
import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .runner import run_simulation

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="eSim-Cloud Sim Worker",
    version="1.0.0",
    description="Standalone ngspice simulation runner for eSim-Cloud.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class SimulationRequest(BaseModel):
    netlist: str = Field(..., description="Raw SPICE netlist text")
    job_id: str | None = Field(None, description="Opaque job identifier")
    timeout: int = Field(300, ge=1, le=600, description="Max execution seconds")


class SimulationResponse(BaseModel):
    job_id: str | None = None
    success: bool
    data: dict | None = None
    error: str | None = None
    error_help: dict | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """Liveness probe endpoint."""
    return {"status": "healthy"}


@app.post("/simulate", response_model=SimulationResponse)
async def simulate(body: SimulationRequest):
    """
    Run an ngspice simulation and return parsed results.

    Returns HTTP 200 even on simulation failure so the caller can inspect
    the structured error payload.  Only returns 5xx on infrastructure errors.
    """
    logger.info("Received simulation request  job_id=%s  timeout=%d", body.job_id, body.timeout)

    if not body.netlist.strip():
        raise HTTPException(status_code=400, detail="netlist must not be empty")

    result = run_simulation(body.netlist, execution_timeout=body.timeout)

    if "fail" in result:
        logger.warning("Simulation failed  job_id=%s  reason=%s", body.job_id, result["fail"][:120])
        return SimulationResponse(
            job_id=body.job_id,
            success=False,
            error=result.get("fail"),
            error_help=result.get("error_help"),
        )

    logger.info("Simulation succeeded  job_id=%s", body.job_id)
    return SimulationResponse(
        job_id=body.job_id,
        success=True,
        data=result,
    )


# ---------------------------------------------------------------------------
# Uvicorn entry-point (python -m uvicorn app.main:app --host 0.0.0.0 --port 8001)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", 8001)),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )
