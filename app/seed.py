"""种子数据：造一批真实感的设备与预约，其中刻意留了「明天上午已被占」用于演示冲突检测。

用法：
    python -m app.seed          # 若 db.json 不存在则生成
    python -m app.seed --reset  # 强制重置（演示前调用）
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "db.json"

DEVICES = [
    {"id": "D01", "name": "高效液相色谱仪", "model": "Agilent 1260", "location": "实验楼 A201", "maintenance": False,
     "note": "需提前配制流动相"},
    {"id": "D02", "name": "气相色谱质谱联用仪", "model": "Shimadzu QP2020", "location": "实验楼 A203", "maintenance": False,
     "note": "操作需持证"},
    {"id": "D03", "name": "紫外可见分光光度计", "model": "Shimadzu UV-2600", "location": "实验楼 A205", "maintenance": False,
     "note": ""},
    {"id": "D04", "name": "高速冷冻离心机", "model": "Eppendorf 5810R", "location": "实验楼 B102", "maintenance": False,
     "note": "配平后使用"},
    {"id": "D05", "name": "荧光倒置显微镜", "model": "Olympus BX53", "location": "实验楼 B105", "maintenance": True,
     "note": "维护中：更换光源，预计 3 天"},
    {"id": "D06", "name": "恒温振荡培养箱", "model": "上海一恒 THZ-98A", "location": "实验楼 B108", "maintenance": False,
     "note": ""},
    {"id": "D07", "name": "超纯水系统", "model": "Millipore Milli-Q", "location": "实验楼 A101", "maintenance": False,
     "note": "公用设备，取水无需预约也可"},
    {"id": "D08", "name": "电子天平（万分之一）", "model": "Mettler ME204", "location": "实验楼 A103", "maintenance": False,
     "note": ""},
]


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="minutes")


def build() -> dict:
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    tomorrow = (now + timedelta(days=1)).replace(hour=9)
    yesterday = (now - timedelta(days=1)).replace(hour=14)

    reservations = [
        # ⭐ 明天 09:00–11:00 D01 已被占 —— 演示冲突用这个时段去约
        {
            "id": "R001", "device_id": "D01", "device_name": "高效液相色谱仪",
            "user": "李思远", "purpose": "毕业设计：丹参酮含量测定",
            "start": _iso(tomorrow), "end": _iso(tomorrow + timedelta(hours=2)),
            "status": "approved", "created_at": _iso(now),
        },
        # 明天 14:00–16:00 D04 已占
        {
            "id": "R002", "device_id": "D04", "device_name": "高速冷冻离心机",
            "user": "王雨桐", "purpose": "生化实验课 · 第 5 组",
            "start": _iso(tomorrow.replace(hour=14)), "end": _iso(tomorrow.replace(hour=16)),
            "status": "approved", "created_at": _iso(now),
        },
        # 待审批
        {
            "id": "R003", "device_id": "D02", "device_name": "气相色谱质谱联用仪",
            "user": "陈昊", "purpose": "课题：环境样品 VOCs 分析",
            "start": _iso(tomorrow.replace(hour=10)), "end": _iso(tomorrow.replace(hour=13)),
            "status": "pending", "created_at": _iso(now),
        },
        # 历史：已使用
        {
            "id": "R004", "device_id": "D03", "device_name": "紫外可见分光光度计",
            "user": "张若溪", "purpose": "分析化学实验",
            "start": _iso(yesterday), "end": _iso(yesterday + timedelta(hours=3)),
            "status": "approved", "created_at": _iso(yesterday - timedelta(days=1)),
        },
        # 历史：被驳回
        {
            "id": "R005", "device_id": "D05", "device_name": "荧光倒置显微镜",
            "user": "刘一帆", "purpose": "细胞形态观察",
            "start": _iso(yesterday), "end": _iso(yesterday + timedelta(hours=2)),
            "status": "rejected", "reject_reason": "设备维护中，改期至下周",
            "created_at": _iso(yesterday - timedelta(days=1)),
        },
    ]

    return {"devices": DEVICES, "reservations": reservations}


def main() -> int:
    reset = "--reset" in sys.argv
    if DB_PATH.exists() and not reset:
        print(f"  已存在，跳过：{DB_PATH}")
        print("  如需重置，加 --reset")
        return 0
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.write_text(json.dumps(build(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✅ 已生成 {DB_PATH}")
    print(f"     设备 {len(DEVICES)} 台 / 预约 5 条")
    print("  ⭐ 演示冲突：对 D01 预约明天 09:30–10:30（与 R001 冲突）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
