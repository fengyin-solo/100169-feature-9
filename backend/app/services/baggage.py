"""行李装卸业务规则：状态流转、分批登记、班组交接与筛选口径都收在这里。

分批明细直接挂在装卸单上（entry["batches"]），列表、汇总、导出都从同一份数据计算，
保证分批合计口径一致；数据落在服务端仓库里，前端刷新后重新拉取即可恢复。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "baggage"
REQUIRED_FIELDS = ["装卸单号", "关联航班", "行李件数"]
OPTIONAL_FIELDS = ["装卸车辆", "作业班组", "开始时刻", "完成时刻"]
STATUS_ORDER = ["待作业", "装卸中", "已完成", "已取消"]
ACTION_RULES = {"安排作业": "装卸中", "确认完成": "已完成", "取消作业": "已取消"}
NEGATIVE_ACTIONS: list[str] = []
BATCH_REQUIRED_FIELDS = ["装卸车辆", "行李件数", "作业班组", "开始时刻"]


def _parse_count(value: Any) -> int | None:
    """把行李件数解析成整数；登记成非数字时返回 None，比较时跳过而不是报错。"""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class BaggageService:
    # ------------------------------------------------------------------ 读取
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("装卸单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._serialize(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self._serialize(entry, with_detail=True)

    def summary(self) -> dict[str, Any]:
        """汇总指标：与列表共用 _serialize，分批合计、差异单数口径保持一致。"""
        rows = [self._serialize(row) for row in store.rows(MODULE)]
        registered_total = 0
        for row in rows:
            parsed = _parse_count(row.get("行李件数"))
            if parsed is not None:
                registered_total += parsed
        status_count = {status: 0 for status in STATUS_ORDER}
        for row in rows:
            status = str(row.get("status") or "")
            if status in status_count:
                status_count[status] += 1
        return {
            "装卸单数": len(rows),
            "登记件数合计": registered_total,
            "分批合计": sum(int(row["分批合计"]) for row in rows),
            "差异单数": sum(1 for row in rows if row["差异提醒"]),
            "已交接单数": sum(1 for row in rows if row["已交接"]),
            "状态分布": status_count,
        }

    # ------------------------------------------------------------------ 登记
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        registered = _parse_count(values.get("行李件数"))
        if registered is None or registered < 0:
            return None, ["行李件数（需为非负整数）"]
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["行李件数"] = registered
        for field in OPTIONAL_FIELDS:
            if str(values.get(field) or "").strip():
                entry[field] = str(values.get(field)).strip()
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["batches"] = []
        entry["交接历史"] = []
        rows.append(entry)
        return self._serialize(entry, with_detail=True), []

    def add_batch(self, entry_id: int, values: dict[str, Any]) -> dict[str, Any]:
        """登记一个分批：车辆、件数、班组、开始时刻必填，完成时刻可后补。

        合计与装卸单登记件数不符时只在 warning 里提醒，不阻断保存；已交接装卸单
        若仍以原班组身份登记，按只读拒绝。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": f"装卸单 {entry_id} 不存在或已归档", "warning": None}
        missing = [field for field in BATCH_REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return {"ok": False, "message": f"缺少必填字段：{'、'.join(missing)}", "warning": None}
        count = _parse_count(values.get("行李件数"))
        if count is None or count <= 0:
            return {"ok": False, "message": "分批行李件数需为正整数", "warning": None}
        team = str(values.get("作业班组")).strip()
        current_team = str(entry.get("作业班组") or "").strip()
        if entry.get("已交接") and team != current_team:
            return {
                "ok": False,
                "message": f"装卸单已交接给{current_team}，{team}仅可查看（原班组只读），分批登记被拒绝",
                "warning": None,
            }
        batches = entry.setdefault("batches", [])
        batch = {
            "批次号": max((int(batch.get("批次号", 0)) for batch in batches), default=0) + 1,
            "装卸车辆": str(values.get("装卸车辆")).strip(),
            "行李件数": count,
            "作业班组": team,
            "开始时刻": str(values.get("开始时刻")).strip(),
            "完成时刻": str(values.get("完成时刻") or "").strip(),
            "登记时刻": _now(),
        }
        batches.append(batch)
        entry.setdefault("交接历史", [])
        warning = ""
        registered = _parse_count(entry.get("行李件数"))
        total = self._batch_total(entry)
        if registered is not None and total != registered:
            warning = (
                f"提醒：分批合计 {total} 件与装卸单登记 {registered} 件不符"
                f"（差 {registered - total} 件），已照常保存"
            )
        serialized = self._serialize(entry, with_detail=True)
        return {
            "ok": True,
            "message": f"第 {batch['批次号']} 批已登记",
            "warning": warning or None,
            "entry": serialized,
            "batch_total": total,
        }

    # ------------------------------------------------------------------ 交接
    def handover(self, ids: list[int], team: str | None) -> dict[str, Any]:
        """把选中的装卸单一次交接给另一个班组；班组空缺、重复交接逐条拒绝说明。"""
        if not ids:
            return {"ok": False, "message": "未选择要交接的装卸单", "results": []}
        target = str(team or "").strip()
        if not target:
            results = []
            for raw_id in ids:
                entry = store.find(MODULE, raw_id)
                label = str(entry.get("装卸单号")) if entry is not None else f"#{raw_id}"
                results.append({
                    "id": raw_id,
                    "label": label,
                    "ok": False,
                    "message": "目标班组为空（班组空缺），本条交接被拒绝",
                })
            return {"ok": False, "message": "班组空缺，本次交接全部拒绝", "results": results}

        results: list[dict[str, Any]] = []
        ok_count = 0
        for raw_id in ids:
            entry = store.find(MODULE, raw_id)
            if entry is None:
                results.append({
                    "id": raw_id,
                    "label": f"#{raw_id}",
                    "ok": False,
                    "message": f"装卸单 {raw_id} 不存在或已归档",
                })
                continue
            label = str(entry.get("装卸单号") or f"#{raw_id}")
            current = str(entry.get("作业班组") or "").strip()
            if entry.get("已交接"):
                results.append({
                    "id": raw_id,
                    "label": label,
                    "ok": False,
                    "message": f"该单已交接给{current or '其他班组'}，重复交接被拒绝",
                })
                continue
            if current and current == target:
                results.append({
                    "id": raw_id,
                    "label": label,
                    "ok": False,
                    "message": f"该单已在{target}作业，无需重复交接",
                })
                continue
            entry["已交接"] = True
            entry["原班组"] = current
            entry["作业班组"] = target
            entry.setdefault("交接历史", []).append({
                "原班组": current or "（未登记班组）",
                "新班组": target,
                "交接时刻": _now(),
            })
            ok_count += 1
            results.append({
                "id": raw_id,
                "label": label,
                "ok": True,
                "message": f"已交接给{target}，原班组{current or '（未登记）'}转为只读",
            })
        rejected = len(ids) - ok_count
        message = f"交接完成 {ok_count} 条，拒绝 {rejected} 条"
        return {"ok": rejected == 0, "message": message, "results": results}

    # ------------------------------------------------------------------ 动作
    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"装卸单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于行李装卸可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return self._serialize(entry), f"装卸单已{action}"

    # ------------------------------------------------------------------ 内部
    @staticmethod
    def _batch_total(entry: dict[str, Any]) -> int:
        return sum(
            (_parse_count(batch.get("行李件数")) or 0)
            for batch in entry.get("batches", [])
        )

    def _serialize(self, entry: dict[str, Any], *, with_detail: bool = False) -> dict[str, Any]:
        """统一出口：补齐分批合计、差异提醒、交接标记；列表与汇总都走这里。"""
        row = dict(entry)
        batches = [dict(batch) for batch in entry.get("batches", [])]
        total = sum((_parse_count(batch.get("行李件数")) or 0) for batch in batches)
        registered = _parse_count(entry.get("行李件数"))
        row["分批合计"] = total
        row["分批数"] = len(batches)
        row["差异提醒"] = ""
        if batches and registered is not None and total != registered:
            row["差异提醒"] = (
                f"分批合计 {total} 件与登记 {registered} 件不符（差 {registered - total} 件）"
            )
        row["已交接"] = bool(entry.get("已交接"))
        if with_detail:
            row["batches"] = batches
            row["交接历史"] = [dict(item) for item in entry.get("交接历史", [])]
        else:
            row.pop("batches", None)
            row.pop("交接历史", None)
        return row
