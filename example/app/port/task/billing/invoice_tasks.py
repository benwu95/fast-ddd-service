from uuid import UUID

from fast_ddd_port.models import MessageModel, Timestamp
from fast_ddd_port.tasks import TaskEnvelope, TaskRegistry

from app.adapter.controller.billing.invoice_controller import InvoiceController
from app.adapter.controller.billing.task_names import (
    DAILY_SUMMARY_SCHEDULE,
    SEND_DAILY_SUMMARY,
    SEND_VOID_NOTICE,
)
from app.core.billing.domain.invoice import InvoiceId

controller = InvoiceController()


class VoidNoticeData(MessageModel):
    invoice_id: UUID


class DailySummaryData(MessageModel):
    since: Timestamp


async def send_void_notice(_: TaskEnvelope, data: VoidNoticeData) -> None:
    await controller.send_void_notice(InvoiceId(data.invoice_id))


async def send_daily_summary(_: TaskEnvelope, data: DailySummaryData) -> None:
    await controller.send_daily_summary(data.since)


def register(registry: TaskRegistry) -> None:
    registry.task(SEND_VOID_NOTICE, VoidNoticeData, send_void_notice)
    registry.task(SEND_DAILY_SUMMARY, DailySummaryData, send_daily_summary)
    registry.cron(DAILY_SUMMARY_SCHEDULE, "0 1 * * *", controller.enqueue_daily_summaries)
