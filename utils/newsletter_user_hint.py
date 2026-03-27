"""одна строка про следующую рассылку для экрана «подписка» (время по МСК)"""
from datetime import timedelta
from zoneinfo import ZoneInfo

from config import (
    NEWSLETTER_ENABLED,
    NEWSLETTER_GOOGLE_DOC_ID,
    NEWSLETTER_WEEK_SPACING_DAYS,
)
from database.models import Database
from newsletter.weekly_job import _parse_anchor_iso

_MSK = ZoneInfo("Europe/Moscow")


async def get_subscription_newsletter_footer(db: Database, user_id: int) -> str:
    """пустая строка или блок с датой/временем следующего слота по графику (как в прод-тике)"""
    if not NEWSLETTER_ENABLED or not NEWSLETTER_GOOGLE_DOC_ID:
        return ""

    if user_id not in await db.newsletter_get_recipient_user_ids():
        return ""

    await db.newsletter_ensure_user(user_id)
    progress = await db.newsletter_get_progress(user_id)
    anchor = _parse_anchor_iso(progress.get("anchor_at") if progress else None)
    if anchor is None:
        await db.newsletter_backfill_anchor_from_subscription(user_id)
        progress = await db.newsletter_get_progress(user_id)
        anchor = _parse_anchor_iso(progress.get("anchor_at") if progress else None)

    if anchor is None:
        return "\n\n📬 Следующая рассылка: время уточняется; расписание ведётся по МСК."

    next_w = int(progress.get("next_week") or 1)
    due = anchor + timedelta(days=NEWSLETTER_WEEK_SPACING_DAYS * (next_w - 1))
    due_msk = due.astimezone(_MSK)
    fmt = due_msk.strftime("%d.%m.%Y %H:%M")
    return f"\n\n📬 Следующая рассылка: {fmt} (МСК)."
