"""行李装卸接口：维护装卸单，覆盖分批登记、班组交接、状态流转与汇总导出。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    BatchActionResult,
    BatchPayload,
    EntryPayload,
    HandoverPayload,
    HandoverResult,
    PageResult,
)
from app.services.baggage import BaggageService

router = APIRouter(prefix="/api/baggage", tags=["行李装卸"])

service = BaggageService()

LIST_FIELDS = ["装卸单号", "关联航班", "登记件数", "装卸车辆", "作业班组", "开始时刻", "完成时刻", "分批合计", "件数不符", "装卸状态"]
STATUSES = ["待作业", "装卸中", "已完成", "已取消"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按装卸单号检索"),
    status: str | None = Query(default=None, description="待作业、装卸中、已完成、已取消"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按装卸单号与状态过滤行李装卸列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary")
def summary() -> dict[str, Any]:
    """汇总指标与列表同源：分批合计、件数不符口径完全一致。"""
    return service.summary()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出行李装卸清单：返回当前过滤条件下的全量数据，含分批明细与合计。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "baggage", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条装卸单明细，含分批明细与交接记录；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"装卸单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条装卸单，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="装卸单已登记", entry=entry)


@router.post("/batches/handover", response_model=HandoverResult)
def handover_batches(payload: HandoverPayload) -> HandoverResult:
    """把选中的多条装卸单一次交接给另一班组；有任一条不满足条件就整体拒绝并逐条说明。"""
    entry_ids, errors, message = service.handover(payload.entry_ids, payload.target_team)
    if errors:
        return HandoverResult(ok=False, message="交接未执行：存在不允许交接的装卸单", errors=errors)
    entries = [service.get_entry(entry_id) for entry_id in entry_ids]
    return HandoverResult(
        ok=True,
        message=message,
        entry_ids=entry_ids,
        entries=[entry for entry in entries if entry is not None],
    )


@router.post("/{entry_id}/batches", response_model=BatchActionResult)
def add_batch(entry_id: int, payload: BatchPayload) -> BatchActionResult:
    """按装卸车辆追加一批行李作业记录；件数不符只在 warning 里提醒，不阻断保存。"""
    entry, errors, warning = service.add_batch(entry_id, payload.values)
    if entry is None:
        return BatchActionResult(ok=False, message="；".join(errors))
    message = "分批已登记"
    if warning:
        message = f"分批已登记。{warning}"
    return BatchActionResult(ok=True, message=message, warning=warning, entry=entry)


@router.delete("/{entry_id}/batches/{batch_index}", response_model=BatchActionResult)
def delete_batch(entry_id: int, batch_index: int) -> BatchActionResult:
    """删除一批记录；交接后原班组的历史分批只读，删除会被拒绝。"""
    entry, warning = service.delete_batch(entry_id, batch_index)
    if entry is None:
        return BatchActionResult(ok=False, message=warning)
    return BatchActionResult(
        ok=True,
        message="该批已删除" + (f"。{warning}" if warning else ""),
        warning=warning,
        entry=entry,
    )


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条装卸单执行安排作业、确认完成、取消作业；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
