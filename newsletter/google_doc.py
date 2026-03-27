"""загрузка публичного Google Doc (export txt) и разбор блоков по неделям"""
import logging
import re
from typing import Dict

import aiohttp

logger = logging.getLogger(__name__)

# строки вида "1 неделя", "12 недели", "Неделя 3"
_WEEK_LINE = re.compile(
    r"^\s*(?:(\d+)\s*недел(?:я|и|е|ю|ь)|недел(?:я|и|е|ю|ь)\s*[:.]?\s*(\d+))\s*$",
    re.IGNORECASE | re.UNICODE,
)


def parse_weeks_from_text(raw: str) -> Dict[int, str]:
    """разбирает текст документа на {номер_недели: текст}"""
    if not raw or not raw.strip():
        return {}

    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    weeks: Dict[int, str] = {}
    current_week: int | None = None
    current_lines: list[str] = []

    def flush():
        nonlocal current_week, current_lines
        if current_week is None:
            return
        body = "\n".join(current_lines).strip()
        if body:
            weeks[current_week] = body
        current_lines = []

    for line in lines:
        m = _WEEK_LINE.match(line)
        if m:
            flush()
            num = m.group(1) or m.group(2)
            current_week = int(num)
            continue
        if current_week is not None:
            current_lines.append(line)

    flush()
    return dict(sorted(weeks.items()))


def build_export_url(doc_id: str) -> str:
    doc_id = doc_id.strip()
    return f"https://docs.google.com/document/d/{doc_id}/export?format=txt"


async def fetch_document_text(doc_id: str) -> str:
    """скачивает документ как plain text (доступ: все с ссылкой)"""
    url = build_export_url(doc_id)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; DrMamashovBot/1.0; +https://t.me)",
        "Accept": "text/plain,*/*",
    }
    timeout = aiohttp.ClientTimeout(total=45, connect=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers, allow_redirects=True) as response:
            if response.status != 200:
                body_preview = (await response.text())[:200]
                raise RuntimeError(
                    f"google doc export status={response.status}, preview={body_preview!r}"
                )
            text = await response.text()
    if not text.strip():
        logger.warning("google doc export: пустой текст")
    return text


async def load_weeks(doc_id: str) -> Dict[int, str]:
    """загрузка и парсинг недель из документа"""
    raw = await fetch_document_text(doc_id)
    weeks = parse_weeks_from_text(raw)
    logger.info("google doc: распознано недель: %s", len(weeks))
    return weeks
