"""行李装卸接口：维护装卸单，覆盖安排作业、确认完成、取消作业、分批登记与班组交接。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    BatchResult,
    EntryPayload,
    HandoverPayload,
    HandoverResult,
    PageResult,
)
from app.services.baggage import BaggageService

router = APIRouter(prefix="/api/baggage", tags=["行李装卸"])

service = BaggageService()

LIST_FIELDS = ["装卸单号", "关联航班", "行李件数", "装卸车辆", "作业班组", "开始时刻", "完成时刻", "装卸状态"]
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
    """汇总装卸单数、登记件数、分批合计与差异单数；口径与列表一致。"""
    return service.summary()


@router.post("/handover", response_model=HandoverResult)
def handover(payload: HandoverPayload) -> HandoverResult:
    """把选中的装卸单一次交接给另一个班组；班组空缺、重复交接逐条说明并拒绝。"""
    result = service.handover(payload.ids, payload.team)
    return HandoverResult(ok=result["ok"], message=result["message"], results=result["results"])


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出行李装卸清单：返回当前过滤条件下的全量数据，含分批合计。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "baggage", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条装卸单明细（含分批与交接历史）；不存在时给出可读的错误说明。"""
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


@router.post("/{entry_id}/batches", response_model=BatchResult)
def add_batch(entry_id: int, payload: EntryPayload) -> BatchResult:
    """按装卸车辆登记一个分批；合计与登记件数不符时提醒但不阻断保存。"""
    result = service.add_batch(entry_id, payload.values)
    return BatchResult(
        ok=result["ok"],
        message=result["message"],
        entry=result.get("entry"),
        warning=result.get("warning"),
        batch_total=result.get("batch_total"),
    )


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条装卸单执行安排作业、确认完成、取消作业；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
