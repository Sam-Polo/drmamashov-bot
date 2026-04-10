"""прогон всех недель рассылки для админ-теста: паузы как у продакшна (сжато), без записи в newsletter_progress"""
import asyncio
import html
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError

from config import (
    APP_VERSION,
    NEWSLETTER_TEST_BETWEEN_WEEKS_SEC,
    NEWSLETTER_TEST_FIRST_DELAY_SEC,
)
from database.models import Database
from newsletter.google_doc import load_weeks
from newsletter.weekly_job import _split_telegram_chunks

logger = logging.getLogger(__name__)
_MSK = ZoneInfo("Europe/Moscow")


def _now_msk_str() -> str:
    return datetime.now(_MSK).strftime("%Y-%m-%d %H:%M:%S")


async def run_newsletter_e2e_test(
    bot: Bot,
    db: Database,
    doc_id: str,
    target_user_id: int,
) -> tuple[bool, str]:
    """
    загружает doc, проверяет активную подписку перед каждой неделей,
    имитирует задержку до недели 1 и интервал между неделями (сек из config),
    не меняет next_week / anchor_at в БД.
    """
    first_sec = max(0.0, float(NEWSLETTER_TEST_FIRST_DELAY_SEC))
    between_sec = max(0.0, float(NEWSLETTER_TEST_BETWEEN_WEEKS_SEC))

    try:
        weeks = await load_weeks(doc_id)
    except Exception as e:
        logger.error("newsletter e2e: doc load %s", e, exc_info=True)
        return False, f"документ: {e}"

    if not weeks:
        return False, "в документе нет ни одной недели"

    sorted_weeks = sorted(weeks.keys())

    logger.info(
        "newsletter e2e test старт: МСК=%s, user_id=%s, недель=%s, версия=%s",
        _now_msk_str(),
        target_user_id,
        len(sorted_weeks),
        APP_VERSION,
    )

    await asyncio.sleep(first_sec)
    sent = 0

    for i, wk in enumerate(sorted_weeks):
        week_data = weeks.get(wk, {})
        body = week_data.get("text", "").strip()
        banner_url = week_data.get("banner_url")
        if not body and not banner_url:
            continue

        header = html.escape(f"Неделя {wk}")
        full_text = (
            f"🧪 <b>ТЕСТ рассылки</b> (не рабочая очередь)\n"
            f"📬 <b>{header}</b>\n\n{body}"
        )

        try:
            if banner_url:
                try:
                    await bot.send_photo(chat_id=target_user_id, photo=banner_url)
                except Exception as banner_err:
                    logger.warning("newsletter e2e: баннер неделя %s: %s", wk, banner_err)

            for part in _split_telegram_chunks(full_text):
                await bot.send_message(
                    chat_id=target_user_id,
                    text=part,
                    parse_mode=ParseMode.HTML,
                )
        except TelegramForbiddenError:
            logger.warning("newsletter e2e: user %s заблокировал бота", target_user_id)
            return False, f"user_id={target_user_id} заблокировал бота на неделе {wk}.{warn}"
        except Exception as e:
            logger.error("newsletter e2e: send %s", e, exc_info=True)
            return False, f"ошибка отправки (неделя {wk}): {e}"

        sent += 1
        logger.info(
            "newsletter e2e: МСК=%s, user_id=%s, отправлена тестовая неделя %s (%s/%s)",
            _now_msk_str(),
            target_user_id,
            wk,
            sent,
            len(sorted_weeks),
        )

        if i < len(sorted_weeks) - 1:
            await asyncio.sleep(between_sec)

    return True, (
        f"user_id={target_user_id}: отправлено писем: {sent} (недели {sorted_weeks[0]}…{sorted_weeks[-1]})"
    )
