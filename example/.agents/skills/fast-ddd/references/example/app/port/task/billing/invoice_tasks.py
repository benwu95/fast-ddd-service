from typing import Annotated
from uuid import UUID

from fast_ddd_port.models import MessageModel, Timestamp
from fast_ddd_port.tasks import TaskEnvelope, TaskRegistry
from pydantic import Field

from app.adapter.controller.billing.invoice_controller import BULK_CHUNK_SIZE, InvoiceController
from app.adapter.controller.billing.task_names import (
    DAILY_SUMMARY_SCHEDULE,
    SEND_DAILY_SUMMARY,
    SEND_VOID_NOTICE,
    VOID_INVOICES,
)
from app.core.billing.domain.invoice import CustomerId, InvoiceId
from app.port.billing.fields import Reason

controller = InvoiceController()


class VoidNoticeData(MessageModel):
    invoice_id: UUID


class DailySummaryData(MessageModel):
    since: Timestamp


class VoidInvoicesData(MessageModel):
    customer_id: UUID
    invoice_ids: Annotated[list[UUID], Field(min_length=1, max_length=BULK_CHUNK_SIZE)]
    reason: Reason


async def send_void_notice(_: TaskEnvelope, data: VoidNoticeData) -> None:
    await controller.send_void_notice(InvoiceId(data.invoice_id))


async def void_invoices(_: TaskEnvelope, data: VoidInvoicesData) -> None:
    await controller.void_invoices(
        CustomerId(data.customer_id),
        [InvoiceId(invoice_id) for invoice_id in data.invoice_ids],
        data.reason,
    )


async def send_daily_summary(_: TaskEnvelope, data: DailySummaryData) -> None:
    await controller.send_daily_summary(data.since)


def register(registry: TaskRegistry) -> None:
    registry.task(SEND_VOID_NOTICE, VoidNoticeData, send_void_notice)
    registry.task(SEND_DAILY_SUMMARY, DailySummaryData, send_daily_summary)
    registry.task(VOID_INVOICES, VoidInvoicesData, void_invoices)
    registry.cron(DAILY_SUMMARY_SCHEDULE, "0 1 * * *", controller.enqueue_daily_summaries)
