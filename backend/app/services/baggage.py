"""行李装卸业务规则：分批登记、班组交接、件数核对与状态流转都收在这里。

一条装卸单可以按装卸车辆分多批登记行李件数，每批记录作业班组与开始、完成时刻；
分批合计与登记件数不符时只提醒不阻断。装卸单可多选一次交接给另一班组，交接后
原班组登记的分批即只读；重复交接、目标班组空缺等情形整体拒绝并逐条说明原因。
"""
from __future__ import annotations

import datetime
from typing import Any

from app.store import store

MODULE = "baggage"
REQUIRED_FIELDS = ["装卸单号", "关联航班", "行李件数"]
STATUS_ORDER = ["待作业", "装卸中", "已完成", "已取消"]
ACTION_RULES = {"安排作业": "装卸中", "确认完成": "已完成", "取消作业": "已取消"}
NEGATIVE_ACTIONS = []

BATCH_FIELDS = ["装卸车辆", "作业班组", "开始时刻", "完成时刻", "行李件数"]


def _to_int(value: Any) -> int | None:
    """把前端提交的件数宽松转成非负整数；转不了就返回 None，由调用方决定如何提示。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = int(text)
    except ValueError:
        return None
    return number if number >= 0 else None


class BaggageService:
    # ------------------------------------------------------------------ 查询
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [self._serialize(row) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("装卸单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._serialize(entry) if entry is not None else None

    # ------------------------------------------------------------------ 登记
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [
            field
            for field in REQUIRED_FIELDS
            if not str(values.get(field) if values.get(field) is not None else "").strip()
        ]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["batches"] = []
        entry["handovers"] = []
        rows.append(entry)
        return self._serialize(entry), []

    # ------------------------------------------------------------------ 分批
    def add_batch(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[str], str]:
        """给装卸单追加一批车辆作业记录。返回（单据、字段级错误、不阻断提醒）。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, [f"装卸单 {entry_id} 不存在或已归档"], ""

        missing = [
            field
            for field in BATCH_FIELDS
            if not str(values.get(field) if values.get(field) is not None else "").strip()
        ]
        if missing:
            return None, [f"缺少必填字段：{'、'.join(missing)}"], ""

        count = _to_int(values.get("行李件数"))
        if count is None:
            return None, ["行李件数需填写为不小于 0 的整数"], ""

        start_at = str(values["开始时刻"]).strip()
        finish_at = str(values["完成时刻"]).strip()
        if finish_at < start_at:
            return None, ["完成时刻不能早于开始时刻"], ""

        team = str(values["作业班组"]).strip()
        current_team = self._current_team(entry)
        if current_team and team != current_team:
            return None, [
                f"该装卸单已交接给「{current_team}」，原班组只读，不能再以「{team}」登记分批"
            ], ""

        batch = {
            "装卸车辆": str(values["装卸车辆"]).strip(),
            "作业班组": team,
            "开始时刻": start_at,
            "完成时刻": finish_at,
            "行李件数": count,
        }
        entry.setdefault("batches", []).append(batch)
        return self._serialize(entry), [], self._mismatch_message(entry)

    def delete_batch(
        self, entry_id: int, batch_index: int
    ) -> tuple[dict[str, Any] | None, str]:
        """删除一批记录；交接后归属原班组的历史分批只读，不允许删除。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"装卸单 {entry_id} 不存在或已归档"
        batches = entry.setdefault("batches", [])
        if not 0 <= batch_index < len(batches):
            return None, f"第 {batch_index + 1} 批记录不存在，可能已被删除"
        if self._batch_locked(entry, batch_index):
            return None, "该批已随班组交接归档，原班组只读，不能删除"
        batches.pop(batch_index)
        return self._serialize(entry), self._mismatch_message(entry)

    # ------------------------------------------------------------------ 交接
    def handover(
        self, entry_ids: list[Any], target_team: str
    ) -> tuple[list[int], list[str], str]:
        """把多条装卸单一次交接给另一班组。

        先整体校验、逐条收集问题，任一条不通过就全部不动；全部通过才落库。
        返回（成功交接的单据 id、逐条错误说明、成功提示）。
        """
        team = str(target_team or "").strip()
        errors: list[str] = []

        if not entry_ids:
            return [], ["未选择任何装卸单，无法交接"], ""

        normalized: list[int] = []
        for raw_id in entry_ids:
            try:
                normalized.append(int(raw_id))
            except (TypeError, ValueError):
                errors.append(f"装卸单「{raw_id}」标识无效，已跳过")
        if errors:
            return [], errors, ""

        if not team:
            errors.append("交接目标班组为空，请先选择接收班组")

        candidates: list[dict[str, Any]] = []
        for entry_id in normalized:
            entry = store.find(MODULE, entry_id)
            label = f"装卸单 {entry_id}"
            if entry is None:
                errors.append(f"{label}：不存在或已归档，不能交接")
                continue
            label = f"装卸单 {entry.get('装卸单号', entry_id)}"
            if entry.get("handovers"):
                last = entry["handovers"][-1]
                errors.append(
                    f"{label}：已交接给「{last.get('toTeam')}」，不能重复交接"
                )
                continue
            if team and self._current_team(entry) == team:
                errors.append(f"{label}：当前作业班组就是「{team}」，无需重复交接")
                continue
            candidates.append(entry)

        if errors:
            return [], errors, ""

        handed_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        for entry in candidates:
            from_team = self._current_team(entry)
            entry.setdefault("handovers", []).append({
                "fromTeam": from_team,
                "toTeam": team,
                "handedAt": handed_at,
                "batchCount": len(entry.get("batches") or []),
            })
        return [int(row["id"]) for row in candidates], [], (
            f"已将 {len(candidates)} 条装卸单交接给班组「{team}」，原班组分批已转为只读"
        )

    # ------------------------------------------------------------------ 状态
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
        return self._serialize(entry), f"装卸单已{action}"

    # ------------------------------------------------------------------ 汇总
    def summary(self) -> dict[str, Any]:
        """列表与汇总共用同一套口径，保证分批合计在两处永远一致。"""
        rows = [self._serialize(row) for row in store.rows(MODULE)]
        mismatched = [row for row in rows if row.get("件数不符")]
        return {
            "装卸单总数": len(rows),
            "登记行李件数合计": sum(int(row.get("登记件数") or 0) for row in rows),
            "分批行李件数合计": sum(int(row.get("分批合计") or 0) for row in rows),
            "分批批次数": sum(int(row.get("分批数") or 0) for row in rows),
            "件数不符单数": len(mismatched),
            "件数不符单号": [row.get("装卸单号") for row in mismatched],
            "待作业单数": sum(1 for row in rows if row.get("status") == STATUS_ORDER[0]),
        }

    # ------------------------------------------------------------------ 内部
    def _current_team(self, entry: dict[str, Any]) -> str:
        handovers = entry.get("handovers") or []
        if handovers:
            return str(handovers[-1].get("toTeam") or "")
        # 未交接过：以最近一批的登记班组作为当前班组；一批都没有就是尚未派班
        batches = entry.get("batches") or []
        return str(batches[-1].get("作业班组") or "") if batches else ""

    def _batch_locked(self, entry: dict[str, Any], batch_index: int) -> bool:
        """该批是否在某次交接时点之前就已存在——是则归属原班组，只读。"""
        return any(
            batch_index < int(handover.get("batchCount", 0))
            for handover in (entry.get("handovers") or [])
            if handover.get("batchCount") is not None
        )

    def _batch_total(self, entry: dict[str, Any]) -> int:
        return sum(
            _to_int(batch.get("行李件数")) or 0
            for batch in entry.get("batches") or []
        )

    def _mismatch_message(self, entry: dict[str, Any]) -> str:
        batches = entry.get("batches") or []
        if not batches:
            return ""
        registered = _to_int(entry.get("行李件数"))
        if registered is None:
            return ""
        total = self._batch_total(entry)
        if total == registered:
            return ""
        return f"分批合计 {total} 件与装卸单登记的 {registered} 件不符，请核对（仍可保存）"

    def _serialize(self, entry: dict[str, Any]) -> dict[str, Any]:
        """对外视图：把分批、交接记录拍平成列表/汇总需要的派生字段。

        所有合计只在这里按同一份 batches 计算，列表、详情、导出、汇总取到的
        分批合计必然一致；存储在内存仓库里，刷新页面不会丢。
        """
        batches: list[dict[str, Any]] = entry.get("batches") or []
        handovers: list[dict[str, Any]] = entry.get("handovers") or []

        locked_indexes: set[int] = set()
        for handover in handovers:
            cutoff = int(handover.get("batchCount", 0))
            locked_indexes.update(range(cutoff))

        batch_views: list[dict[str, Any]] = []
        total = 0
        vehicles: list[str] = []
        starts: list[str] = []
        finishes: list[str] = []
        for index, batch in enumerate(batches):
            count = _to_int(batch.get("行李件数")) or 0
            total += count
            vehicle = str(batch.get("装卸车辆") or "")
            if vehicle and vehicle not in vehicles:
                vehicles.append(vehicle)
            starts.append(str(batch.get("开始时刻") or ""))
            finishes.append(str(batch.get("完成时刻") or ""))
            batch_views.append({
                "序号": index + 1,
                "装卸车辆": batch.get("装卸车辆"),
                "作业班组": batch.get("作业班组"),
                "开始时刻": batch.get("开始时刻"),
                "完成时刻": batch.get("完成时刻"),
                "行李件数": count,
                "只读": index in locked_indexes,
            })

        registered = _to_int(entry.get("行李件数"))
        mismatch = bool(batches) and registered is not None and total != registered
        current_team = self._current_team(entry)

        view = dict(entry)
        view["登记件数"] = registered if registered is not None else entry.get("行李件数")
        view["分批合计"] = total
        view["分批数"] = len(batch_views)
        view["件数不符"] = mismatch
        view["分批明细"] = batch_views
        view["装卸车辆"] = "、".join(vehicles)
        view["作业班组"] = current_team
        view["开始时刻"] = min(starts) if starts else ""
        view["完成时刻"] = max(finishes) if finishes else ""
        view["已交接"] = bool(handovers)
        view["交接记录"] = handovers
        view["pending"] = entry.get("status") != STATUS_ORDER[-1]
        view["abnormal"] = mismatch
        return view
