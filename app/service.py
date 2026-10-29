"""业务层：冲突检测、可用时段推荐、利用率统计。

MVP 的核心价值就在 check_conflict —— 它替代了「管理员凭记忆判断」。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from . import store

WORK_START, WORK_END = 8, 22      # 实验室开放时段
SLOT_MINUTES = 60                  # 推荐时段的粒度


class ConflictError(ValueError):
    """时段冲突。携带冲突的那条预约，供接口返回给前端。"""

    def __init__(self, message: str, conflicting: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.conflicting = conflicting


def _parse(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", ""))
    except ValueError as exc:
        raise ValueError(f"时间格式不对：{ts!r}，应为 YYYY-MM-DDTHH:MM") from exc


def _overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """半开区间重叠：仍允许「上一个 11:00 结束、下一个 11:00 开始」。"""
    return a_start < b_end and a_end > b_start


# ---------- 核心：冲突检测 ----------

def check_conflict(device_id: str, start: str, end: str, exclude_id: str | None = None) -> dict[str, Any] | None:
    """返回冲突的那条预约；无冲突返回 None。"""
    s, e = _parse(start), _parse(end)
    if s >= e:
        raise ValueError("结束时间必须晚于开始时间")
    if s < datetime.now() - timedelta(minutes=5):
        raise ValueError("不能预约已经过去的时段")
    if s.date() != e.date():
        raise ValueError("不支持跨天预约，请拆成两段")
    if s.hour < WORK_START or (e.hour, e.minute) > (WORK_END, 0):
        raise ValueError(f"只能在 {WORK_START}:00–{WORK_END}:00 之间预约")

    for r in store.list_reservations(device_id=device_id):
        if r.get("status") not in ("pending", "approved"):
            continue
        if exclude_id and r.get("id") == exclude_id:
            continue
        if _overlap(s, e, _parse(r["start"]), _parse(r["end"])):
            return r
    return None


def suggest_slots(device_id: str, start: str, hours: int = 2, limit: int = 3) -> list[str]:
    """冲突时给出同一天最近的可用起点。"""
    day = _parse(start).replace(hour=0, minute=0, second=0, microsecond=0)
    taken = [
        (_parse(r["start"]), _parse(r["end"]))
        for r in store.list_reservations(device_id=device_id)
        if r.get("status") in ("pending", "approved")
    ]
    out: list[str] = []
    t = day + timedelta(hours=WORK_START)
    while t + timedelta(hours=hours) <= day + timedelta(hours=WORK_END):
        e = t + timedelta(hours=hours)
        if not any(_overlap(t, e, ts, te) for ts, te in taken):
            out.append(t.isoformat(timespec="minutes"))
            if len(out) >= limit:
                break
        t += timedelta(minutes=SLOT_MINUTES)
    return out


# ---------- 设备状态 ----------

def device_runtime_status(device: dict[str, Any], now: datetime | None = None) -> str:
    """idle（空闲）/ busy（使用中）/ maintenance（维护）。"""
    if device.get("maintenance"):
        return "maintenance"
    now = now or datetime.now()
    for r in store.list_reservations(device_id=device.get("id")):
        if r.get("status") != "approved":
            continue
        if _parse(r["start"]) <= now < _parse(r["end"]):
            return "busy"
    return "idle"


def list_devices_with_status() -> list[dict[str, Any]]:
    out = []
    for d in store.list_devices():
        item = dict(d)
        item["runtime_status"] = device_runtime_status(d)
        upcoming = [
            r for r in store.list_reservations(device_id=d.get("id"))
            if r.get("status") == "approved" and _parse(r["end"]) > datetime.now()
        ]
        item["next_booking"] = upcoming[0] if upcoming else None
        out.append(item)
    return out


# ---------- 创建 / 审批 ----------

def create_reservation(payload: dict[str, Any]) -> dict[str, Any]:
    device_id = (payload.get("device_id") or "").strip()
    device = store.get_device(device_id)
    if not device:
        raise ValueError(f"设备不存在：{device_id}")
    if device.get("maintenance"):
        raise ConflictError("该设备在维护中，暂不可预约")

    start, end = payload.get("start", ""), payload.get("end", "")
    conflict = check_conflict(device_id, start, end)
    if conflict:
        raise ConflictError(
            f"时段冲突：{conflict.get('user')} 已在 {conflict['start'][11:16]}–{conflict['end'][11:16]} 预约",
            conflict,
        )

    item = {
        "id": store.next_reservation_id(),
        "device_id": device_id,
        "device_name": device.get("name"),
        "user": (payload.get("user") or "").strip(),
        "purpose": (payload.get("purpose") or "").strip(),
        "start": start,
        "end": end,
        "status": "pending",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not item["user"]:
        raise ValueError("请填写预约人")
    if not item["purpose"]:
        raise ValueError("请填写用途（哪门课 / 哪个课题）")
    return store.add_reservation(item)


def approve(rid: str) -> dict[str, Any]:
    r = store.get_reservation(rid)
    if not r:
        raise ValueError("预约不存在")
    if r.get("status") != "pending":
        raise ValueError(f"当前状态是 {r.get('status')}，不能审批")
    conflict = check_conflict(r["device_id"], r["start"], r["end"], exclude_id=rid)
    if conflict:
        raise ConflictError(
            f"审批时发现冲突：{conflict.get('user')} 也约了这段时间", conflict
        )
    store.update_reservation(rid, status="approved")
    return store.get_reservation(rid)


def reject(rid: str, reason: str = "") -> dict[str, Any]:
    r = store.get_reservation(rid)
    if not r:
        raise ValueError("预约不存在")
    store.update_reservation(rid, status="rejected", reject_reason=reason or "未填写原因")
    return store.get_reservation(rid)


# ---------- 统计 ----------

def stats() -> dict[str, Any]:
    devices = store.list_devices()
    res = store.list_reservations()
    approved = [r for r in res if r.get("status") == "approved"]

    hours_by_device: dict[str, float] = {}
    for r in approved:
        try:
            dur = (_parse(r["end"]) - _parse(r["start"])).total_seconds() / 3600
        except ValueError:
            continue
        hours_by_device[r["device_id"]] = hours_by_device.get(r["device_id"], 0) + dur

    rows = []
    for d in devices:
        used = round(hours_by_device.get(d["id"], 0), 1)
        rows.append({"id": d["id"], "name": d["name"], "hours": used, "sessions": sum(
            1 for r in approved if r["device_id"] == d["id"])})
    rows.sort(key=lambda x: x["hours"], reverse=True)

    return {
        "device_count": len(devices),
        "reservation_total": len(res),
        "pending": sum(1 for r in res if r.get("status") == "pending"),
        "approved": len(approved),
        "rejected": sum(1 for r in res if r.get("status") == "rejected"),
        "total_hours": round(sum(hours_by_device.values()), 1),
        "by_device": rows,
        "idle_devices": [d["name"] for d in list_devices_with_status() if d["runtime_status"] == "idle"],
    }
