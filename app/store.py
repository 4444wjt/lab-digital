"""仓储层：JSON 文件存储。MVP 阶段不引入数据库，但把所有读写收在这一层。"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "db.json"
_LOCK = threading.Lock()


def _read() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"devices": [], "reservations": []}
    with DB_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _write(data: dict[str, Any]) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(DB_PATH)


# ---------- 设备 ----------

def list_devices() -> list[dict[str, Any]]:
    return _read().get("devices", [])


def get_device(device_id: str) -> dict[str, Any] | None:
    for d in list_devices():
        if d.get("id") == device_id:
            return d
    return None


# ---------- 预约 ----------

def list_reservations(device_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    items = _read().get("reservations", [])
    if device_id:
        items = [r for r in items if r.get("device_id") == device_id]
    if status:
        items = [r for r in items if r.get("status") == status]
    return sorted(items, key=lambda r: r.get("start", ""))


def get_reservation(rid: str) -> dict[str, Any] | None:
    for r in _read().get("reservations", []):
        if r.get("id") == rid:
            return r
    return None


def add_reservation(item: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        data = _read()
        data.setdefault("reservations", []).append(item)
        _write(data)
    return item


def update_reservation(rid: str, **fields: Any) -> dict[str, Any] | None:
    with _LOCK:
        data = _read()
        for r in data.get("reservations", []):
            if r.get("id") == rid:
                r.update(fields)
                r["updated_at"] = datetime.now().isoformat(timespec="seconds")
                _write(data)
                return r
    return None


def next_reservation_id() -> str:
    items = _read().get("reservations", [])
    n = len(items) + 1
    while any(r.get("id") == f"R{n:03d}" for r in items):
        n += 1
    return f"R{n:03d}"


# ---------- 冲突记录 ----------
# 业务挖掘里说「冲突次数无法证明，因为没有记录」。这里补上：每次提交撞上冲突，
# 都留一条 —— 于是"每学期冲突多少次"从猜测变成可查。

def add_conflict(entry: dict[str, Any]) -> None:
    with _LOCK:
        data = _read()
        data.setdefault("conflicts", []).append(entry)
        _write(data)


def list_conflicts() -> list[dict[str, Any]]:
    return _read().get("conflicts", [])
