"""периодическая рассылка «недель» из Google Doc (якорь от момента подписки + задержка)"""
import asyncio
import html
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile

from config import APP_VERSION, NEWSLETTER_WEEK_SPACING_DAYS
from database.models import Database
from newsletter.google_doc import load_weeks

logger = logging.getLogger(__name__)
_MSK = ZoneInfo("Europe/Moscow")

_job_lock = asyncio.Lock()

# кэш документа между тиками (не дёргать Google каждую минуту)
_doc_cache_id: str | None = None
_doc_cache_weeks: dict | None = None
_doc_cache_mono: float = 0.0
_DOC_CACHE_TTL_SEC = 300.0


def _now_msk_str() -> str:
    return datetime.now(_MSK).strftime("%Y-%m-%d %H:%M:%S")


def _parse_anchor_iso(iso: str | None) -> datetime | None:
    if not iso or not str(iso).strip():
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_MSK)
        else:
            dt = dt.astimezone(_MSK)
        return dt
    except ValueError:
        return None


async def _fetch_banner(url: str) -> BufferedInputFile | None:
    """Возвращает BufferedInputFile для отправки в Telegram.
    Поддерживает base64 data URI (Google Docs HTML export встраивает картинки так)
    и обычные HTTP-URL."""
    try:
        if url.startswith("data:"):
            # data:image/png;base64,XXXX...
            import base64 as _b64
            header, _, b64data = url.partition(",")
            if "base64" not in header or not b64data:
                return None
            data = _b64.b64decode(b64data)
            mime = header.split(";")[0].split(":")[-1] if ":" in header else "image/jpeg"
            ext = mime.split("/")[-1] or "jpg"
            return BufferedInputFile(data, filename=f"banner.{ext}")

        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status == 200:
                    return BufferedInputFile(await resp.read(), filename="banner.jpg")
                logger.warning("banner fetch: статус %s", resp.status)
    except Exception as e:
        logger.warning("banner fetch error: %s", str(e)[:120])
    return None


def _split_telegram_chunks(text: str, limit: int = 4000) -> list[str]:
    """Разбивает текст на части по границам абзацев, не превышая limit символов"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0
    for para in paragraphs:
        addition = (2 if current_parts else 0) + len(para)
        if current_parts and current_len + addition > limit:
            chunks.append("\n\n".join(current_parts))
            current_parts = [para]
            current_len = len(para)
        else:
            current_parts.append(para)
            current_len += addition
    if current_parts:
        chunks.append("\n\n".join(current_parts))
    return chunks


async def _get_weeks_cached(doc_id: str) -> dict:
    global _doc_cache_id, _doc_cache_weeks, _doc_cache_mono
    now_m = time.monotonic()
    if (
        _doc_cache_id == doc_id
        and _doc_cache_weeks is not None
        and (now_m - _doc_cache_mono) < _DOC_CACHE_TTL_SEC
    ):
        return _doc_cache_weeks
    weeks = await load_weeks(doc_id)
    _doc_cache_id = doc_id
    _doc_cache_weeks = weeks
    _doc_cache_mono = now_m
    return weeks


async def run_newsletter_tick(bot: Bot, db: Database, doc_id: str) -> None:
    """один проход: у кого пришёл срок очередной недели — отправить"""
    global _doc_cache_weeks, _doc_cache_id, _doc_cache_mono

    now_msk = datetime.now(_MSK)
    spacing_days = NEWSLETTER_WEEK_SPACING_DAYS

    async with _job_lock:
        logger.debug(
            "newsletter tick: МСК=%s, spacing_days=%s, версия=%s",
            _now_msk_str(),
            spacing_days,
            APP_VERSION,
        )

        try:
            weeks_content = await _get_weeks_cached(doc_id)
        except Exception as e:
            logger.error("newsletter: не удалось загрузить документ: %s", e, exc_info=True)
            _doc_cache_weeks = None
            _doc_cache_id = None
            return

        if not weeks_content:
            logger.warning("newsletter: в документе нет ни одной недели — пропуск")
            return

        user_ids = await db.newsletter_get_recipient_user_ids()
        sent_ok = 0
        skipped = 0
        errors = 0

        for user_id in user_ids:
            try:
                await db.newsletter_ensure_user(user_id)
                progress = await db.newsletter_get_progress(user_id)
                if not progress:
                    continue

                anchor = _parse_anchor_iso(progress.get("anchor_at"))
                if anchor is None:
                    await db.newsletter_backfill_anchor_from_subscription(user_id)
                    progress = await db.newsletter_get_progress(user_id)
                    anchor = _parse_anchor_iso(progress.get("anchor_at") if progress else None)

                if anchor is None:
                    skipped += 1
                    continue

                while True:
                    progress = await db.newsletter_get_progress(user_id)
                    if not progress:
                        break
                    next_w = int(progress.get("next_week") or 1)
                    week_data = weeks_content.get(next_w)
                    if not week_data:
                        logger.warning(
                            "newsletter: user_id=%s ждёт неделю %s, в документе нет (есть недели %s) — стоп",
                            user_id,
                            next_w,
                            sorted(weeks_content.keys()),
                        )
                        skipped += 1
                        break

                    due = anchor + timedelta(days=spacing_days * (next_w - 1))
                    if now_msk < due:
                        break

                    body = week_data["text"]
                    banner_url = week_data.get("banner_url")
                    header = html.escape(f"Неделя {next_w}")
                    full_text = f"📬 <b>{header}</b>\n\n{body}"

                    if banner_url:
                        photo = await _fetch_banner(banner_url)
                        if photo:
                            try:
                                await bot.send_photo(chat_id=user_id, photo=photo)
                            except Exception as banner_err:
                                logger.warning(
                                    "newsletter: не удалось отправить баннер user_id=%s неделя=%s: %s",
                                    user_id,
                                    next_w,
                                    banner_err,
                                )

                    for part in _split_telegram_chunks(full_text):
                        await bot.send_message(
                            chat_id=user_id,
                            text=part,
                            parse_mode=ParseMode.HTML,
                        )

                    await db.newsletter_advance_week(user_id, next_w + 1)
                    sent_ok += 1

            except Exception as e:
                errors += 1
                logger.warning(
                    "newsletter: ошибка для user_id=%s: %s",
                    user_id,
                    e,
                    exc_info=True,
                )

        if sent_ok or errors:
            logger.info(
                "newsletter tick: МСК=%s, отправлено шагов=%s, пропусков=%s, ошибок=%s",
                _now_msk_str(),
                sent_ok,
                skipped,
                errors,
            )
