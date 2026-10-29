"""HTTP 层：只做参数解析与错误映射，业务逻辑全在 service。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import service, store

logging.basicConfig(level=logging.INFO, format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":%(message)s}')
log = logging.getLogger("lab.api")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="实验室设备预约系统 · MVP", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8020", "http://localhost:8020"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReservationIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=32)
    user: str = Field(min_length=1, max_length=32, description="预约人姓名")
    purpose: str = Field(min_length=1, max_length=120, description="哪门课 / 哪个课题")
    start: str = Field(description="YYYY-MM-DDTHH:MM")
    end: str = Field(description="YYYY-MM-DDTHH:MM")


class RejectIn(BaseModel):
    reason: str = Field(default="", max_length=200)


@app.exception_handler(service.ConflictError)
async def _conflict_handler(_, exc: service.ConflictError) -> JSONResponse:
    """冲突不是 500：返回 409 + 冲突详情 + 当天可用时段。"""
    r = exc.conflicting or {}
    slots: list[str] = []
    if r.get("device_id") and r.get("start"):
        try:
            slots = service.suggest_slots(r["device_id"], r["start"])
        except Exception:
            slots = []
    return JSONResponse(
        status_code=409,
        content={
            "error": "conflict",
            "message": str(exc),
            "conflicting": r,
            "suggested_slots": slots,
        },
    )


@app.exception_handler(ValueError)
async def _value_handler(_, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "bad_request", "message": str(exc)})


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "devices": len(store.list_devices())}


@app.get("/api/devices")
async def api_devices() -> dict[str, Any]:
    items = service.list_devices_with_status()
    return {"devices": items, "count": len(items)}


@app.get("/api/reservations")
async def api_reservations(
    device_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    return {"reservations": store.list_reservations(device_id=device_id, status=status)}


@app.post("/api/reservations")
async def api_create(payload: ReservationIn) -> dict[str, Any]:
    log.info('"创建预约 device=%s user=%s"', payload.device_id, payload.user)
    item = service.create_reservation(payload.model_dump())
    return {"reservation": item}


@app.post("/api/reservations/{rid}/approve")
async def api_approve(rid: str) -> dict[str, Any]:
    return {"reservation": service.approve(rid)}


@app.post("/api/reservations/{rid}/reject")
async def api_reject(rid: str, payload: RejectIn) -> dict[str, Any]:
    return {"reservation": service.reject(rid, payload.reason)}


@app.get("/api/stats")
async def api_stats() -> dict[str, Any]:
    return service.stats()


# 静态文件挂根：html=True 时 / 自动返回 index.html；vendor/ 等相对路径也能命中。
# 必须放在所有 API 路由之后注册，否则会拦截 /api/*。
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
