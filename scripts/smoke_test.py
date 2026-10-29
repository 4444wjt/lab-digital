"""冒烟测试：验证前后端关键路径可用。

用法：
    python scripts/smoke_test.py                 # 冒烟（会写一条 +7 天的测试预约）
    python scripts/smoke_test.py --edge          # 追加边界测试

前置：服务已在 127.0.0.1:8020 运行，且已执行 python -m app.seed --reset
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

import httpx

BASE = "http://127.0.0.1:8020"
results: list[tuple[str, bool, str]] = []


def chk(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  — {detail}" if detail else ""))


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="minutes")


# ---------- 冒烟 ----------

def smoke() -> None:
    print("[冒烟 · 基础接口]")
    r = httpx.get(BASE + "/health", timeout=10)
    chk("/health 200", r.status_code == 200, f"devices={r.json().get('devices')}")

    r = httpx.get(BASE + "/api/devices", timeout=10)
    d = r.json()
    chk("/api/devices 200", r.status_code == 200, f"{d.get('count')} 台")
    chk("含空闲设备", any(x["runtime_status"] == "idle" for x in d["devices"]))
    chk("含维护设备", any(x["runtime_status"] == "maintenance" for x in d["devices"]))

    r = httpx.get(BASE + "/api/reservations", timeout=10)
    chk("/api/reservations 200", r.status_code == 200, f"{len(r.json()['reservations'])} 条")

    r = httpx.get(BASE + "/api/stats", timeout=10)
    d = r.json()
    chk("/api/stats 200", r.status_code == 200,
        f"设备{d.get('device_count')} 已通过{d.get('approved')} 机时{d.get('total_hours')}h")

    r = httpx.get(BASE + "/", timeout=10)
    chk("GET / 返回页面", r.status_code == 200 and "实验室" in r.text, f"{len(r.text)} 字符")

    print("\n[冒烟 · 主路径：创建 → 冲突 → 审批]")
    t = (datetime.now() + timedelta(days=7)).replace(hour=9, minute=0, second=0, microsecond=0)
    payload = {
        "device_id": "D03", "user": "冒烟测试员", "purpose": "自动化冒烟",
        "start": iso(t), "end": iso(t + timedelta(hours=1)),
    }
    r = httpx.post(BASE + "/api/reservations", json=payload, timeout=10)
    created = r.json().get("reservation", {}) if r.status_code == 200 else {}
    chk("创建预约", r.status_code == 200, f"单号 {created.get('id')}")

    r = httpx.post(BASE + "/api/reservations", json={**payload, "user": "第二个人"}, timeout=10)
    d = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    chk("重复时段返回 409", r.status_code == 409, (d.get("message") or "")[:44])
    chk("冲突带建议时段", bool(d.get("suggested_slots")),
        str([x[11:16] for x in d.get("suggested_slots", [])]))

    if created.get("id"):
        r = httpx.post(BASE + f"/api/reservations/{created['id']}/approve", timeout=10)
        chk("审批通过", r.status_code == 200 and r.json()["reservation"]["status"] == "approved")


# ---------- 边界 ----------

def edge() -> None:
    print("\n[边界测试]")

    def post(payload: dict):
        return httpx.post(BASE + "/api/reservations", json=payload, timeout=10)

    t = (datetime.now() + timedelta(days=8)).replace(hour=10, minute=0, second=0, microsecond=0)
    good = {"device_id": "D06", "user": "边界", "purpose": "边界测试",
            "start": iso(t), "end": iso(t + timedelta(hours=1))}

    # 1 结束早于开始
    r = post({**good, "start": iso(t + timedelta(hours=2)), "end": iso(t)})
    chk("结束早于开始 → 400", r.status_code == 400, (r.json().get("message") or "")[:36])

    # 2 开始等于结束
    r = post({**good, "start": iso(t), "end": iso(t)})
    chk("起止相同 → 400", r.status_code == 400, (r.json().get("message") or "")[:36])

    # 3 过去时间
    past = (datetime.now() - timedelta(days=1)).replace(hour=10)
    r = post({**good, "start": iso(past), "end": iso(past + timedelta(hours=1))})
    chk("预约过去时段 → 400", r.status_code == 400, (r.json().get("message") or "")[:36])

    # 4 不存在的设备
    r = post({**good, "device_id": "D999"})
    chk("设备不存在 → 400", r.status_code == 400, (r.json().get("message") or "")[:36])

    # 5 维护中的设备
    r = post({**good, "device_id": "D05"})
    chk("维护中设备 → 409", r.status_code == 409, (r.json().get("message") or "")[:36])

    # 6 缺预约人
    r = post({**good, "user": ""})
    chk("缺预约人 → 422/400", r.status_code in (400, 422), f"HTTP {r.status_code}")

    # 7 缺用途
    r = post({**good, "purpose": ""})
    chk("缺用途 → 422/400", r.status_code in (400, 422), f"HTTP {r.status_code}")

    # 8 超长用途（>120 字符）
    r = post({**good, "purpose": "很长" * 100})
    chk("用途超长 → 422", r.status_code == 422, f"HTTP {r.status_code}")

    # 9 时间格式错误
    r = post({**good, "start": "明天上午", "end": "明天中午"})
    chk("时间格式错误 → 400", r.status_code == 400, (r.json().get("message") or "")[:36])

    # 10 跨天长预约（8:00–22:00 是允许的）
    d0 = (datetime.now() + timedelta(days=9)).replace(hour=8, minute=0, second=0, microsecond=0)
    r = post({**good, "start": iso(d0), "end": iso(d0 + timedelta(hours=14))})
    chk("单日 14 小时长预约 → 允许", r.status_code == 200, f"HTTP {r.status_code}")

    # 11 超出开放时段（22:00 后）
    r = post({**good, "start": iso(d0.replace(hour=23)), "end": iso(d0.replace(hour=23, minute=30))})
    chk("超出开放时段 → 400", r.status_code == 400, (r.json().get("message") or "")[:40])

    # 11b 跨天预约
    r = post({**good, "start": iso(d0.replace(hour=21)),
              "end": iso((d0 + timedelta(days=1)).replace(hour=1))})
    chk("跨天预约 → 400", r.status_code == 400, (r.json().get("message") or "")[:40])

    # 12 审批不存在的单号
    r = httpx.post(BASE + "/api/reservations/R999/approve", timeout=10)
    chk("审批不存在单号 → 400", r.status_code == 400, (r.json().get("message") or "")[:36])

    # 13 重复审批
    r = httpx.get(BASE + "/api/reservations?status=pending", timeout=10)
    pend = r.json().get("reservations", [])
    if pend:
        rid = pend[0]["id"]
        httpx.post(BASE + f"/api/reservations/{rid}/approve", timeout=10)
        r2 = httpx.post(BASE + f"/api/reservations/{rid}/approve", timeout=10)
        chk("重复审批 → 400", r2.status_code == 400, (r2.json().get("message") or "")[:36])


def main() -> int:
    try:
        httpx.get(BASE + "/health", timeout=5)
    except Exception as exc:
        print(f"  ❌ 服务未启动（{type(exc).__name__}）：请先运行 uvicorn app.main:app --port 8020")
        return 1

    smoke()
    if "--edge" in sys.argv:
        edge()

    total = len(results)
    passed = sum(1 for _, c, _ in results if c)
    print(f"\n{'=' * 54}")
    print(f"共 {total} 项，通过 {passed}，失败 {total - passed}")
    if passed != total:
        print("失败项：")
        for n, c, d in results:
            if not c:
                print(f"  - {n}  {d}")
    print("=" * 54)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
