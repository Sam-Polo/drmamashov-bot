"""загрузка публичного Google Doc (export html) и разбор блоков по неделям с форматированием"""
import html as _html
import logging
import re
from html.parser import HTMLParser
from typing import Dict, Optional
from urllib.parse import unquote

import aiohttp

logger = logging.getLogger(__name__)

# строки вида "1 неделя", "12 недели", "Неделя 3"
_WEEK_LINE = re.compile(
    r"^\s*(?:(\d+)\s*недел(?:я|и|е|ю|ь)|недел(?:я|и|е|ю|ь)\s*[:.]?\s*(\d+))\s*$",
    re.IGNORECASE | re.UNICODE,
)

_INVISIBLE = "\ufeff\u200b\u200c\u200d\u2060"

_FMT_OPEN_ORDER = ("b", "i", "u", "s")
_FMT_CLOSE_ORDER = ("s", "u", "i", "b")


def _strip_invisible(s: str) -> str:
    return s.strip(_INVISIBLE + " \t\r\n")


def _parse_style(style: str) -> frozenset:
    """Возвращает frozenset активных форматов из строки CSS-стилей"""
    fmts: set = set()
    if re.search(r"font-weight\s*:\s*(700|bold)\b", style):
        fmts.add("b")
    if re.search(r"font-style\s*:\s*italic\b", style):
        fmts.add("i")
    td = re.search(r"text-decoration\s*:\s*([^;]+)", style)
    if td:
        td_val = td.group(1).lower()
        if "underline" in td_val:
            fmts.add("u")
        if "line-through" in td_val:
            fmts.add("s")
    return frozenset(fmts)


def _parse_css_classes(css: str) -> Dict[str, frozenset]:
    """Разбирает <style>-блок: возвращает {имя_класса: набор_форматов}"""
    result: Dict[str, frozenset] = {}
    for m in re.finditer(r"\.([\w-]+)\s*\{([^}]*)\}", css, re.DOTALL):
        fmts = _parse_style(m.group(2))
        if fmts:
            result[m.group(1)] = fmts
    return result


def _unwrap_google_redirect(href: str) -> str:
    """Google Docs оборачивает внешние ссылки в /url?q=... — достаём оригинал"""
    if not href:
        return href
    m = re.search(r"[?&]q=([^&]+)", href)
    return unquote(m.group(1)) if m else href


class _DocParser(HTMLParser):
    """Разбирает HTML-экспорт Google Docs по неделям, конвертируя форматирование в Telegram HTML"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.weeks: Dict[int, dict] = {}

        self._current_week: Optional[int] = None
        self._paragraphs: list[str] = []
        self._current_banner: Optional[str] = None

        # Текущий абзац
        self._para_parts: list[str] = []
        self._in_para: bool = False
        # Стек форматирования: (tag, added_fmts)
        self._fmt_stack: list[tuple] = []
        self._active_fmt: set = set()
        # Стек ссылок: href или None
        self._link_stack: list[Optional[str]] = []

        # CSS-классы из <style> (Google Docs хранит форматирование там)
        self._css_classes: Dict[str, frozenset] = {}
        self._collecting_css: bool = False
        self._css_buf: list[str] = []

        # Скрипты — пропускаем
        self._skip_depth: int = 0

    # ── CSS ──────────────────────────────────────────────────────────────

    def _get_class_fmts(self, class_attr: str) -> frozenset:
        fmts: set = set()
        for cls in class_attr.split():
            fmts |= self._css_classes.get(cls, frozenset())
        return frozenset(fmts)

    # ── Форматирование ────────────────────────────────────────────────────

    def _push_fmt(self, tag: str, fmts: frozenset) -> None:
        added = frozenset(fmts - self._active_fmt)
        self._fmt_stack.append((tag, added))
        if added:
            for f in _FMT_OPEN_ORDER:
                if f in added:
                    self._para_parts.append(f"<{f}>")
            self._active_fmt |= added

    def _pop_fmt(self, tag: str) -> None:
        for idx in range(len(self._fmt_stack) - 1, -1, -1):
            if self._fmt_stack[idx][0] == tag:
                _, added = self._fmt_stack.pop(idx)
                still_needed: set = set()
                for _, fmts in self._fmt_stack:
                    still_needed |= fmts
                to_close = added - still_needed
                if to_close:
                    for f in _FMT_CLOSE_ORDER:
                        if f in to_close:
                            self._para_parts.append(f"</{f}>")
                    self._active_fmt -= to_close
                break

    # ── HTMLParser callbacks ──────────────────────────────────────────────

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attrs_dict = dict(attrs)

        if self._skip_depth > 0:
            self._skip_depth += 1
            return

        if tag == "script":
            self._skip_depth = 1
            return

        if tag == "style":
            self._collecting_css = True
            return

        if tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li"):
            if self._in_para:
                self._close_para()
            self._in_para = True
            self._para_parts = []
            self._fmt_stack = []
            self._active_fmt = set()
            self._link_stack = []
            return

        if tag == "img":
            src = attrs_dict.get("src", "")
            if src and self._current_week is not None and self._current_banner is None:
                self._current_banner = src
            return

        if not self._in_para:
            return

        # Inline-теги внутри абзаца
        if tag in ("b", "strong"):
            self._push_fmt(tag, frozenset({"b"}))
        elif tag in ("i", "em"):
            self._push_fmt(tag, frozenset({"i"}))
        elif tag == "u":
            self._push_fmt(tag, frozenset({"u"}))
        elif tag in ("s", "strike", "del"):
            self._push_fmt(tag, frozenset({"s"}))
        elif tag == "span":
            style = attrs_dict.get("style", "")
            cls = attrs_dict.get("class", "")
            fmts = _parse_style(style) | self._get_class_fmts(cls)
            self._push_fmt(tag, fmts)
        elif tag == "a":
            href = _unwrap_google_redirect(attrs_dict.get("href", ""))
            if href:
                self._link_stack.append(href)
                self._para_parts.append(f'<a href="{_html.escape(href, quote=True)}">')
            else:
                self._link_stack.append(None)
        elif tag == "br":
            self._para_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth > 0:
            self._skip_depth -= 1
            return

        if tag == "style":
            self._collecting_css = False
            self._css_classes = _parse_css_classes("".join(self._css_buf))
            self._css_buf = []
            return

        if tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li"):
            if self._in_para:
                self._close_para()
            return

        if not self._in_para:
            return

        if tag in ("b", "strong", "i", "em", "u", "s", "strike", "del", "span"):
            self._pop_fmt(tag)
        elif tag == "a":
            if self._link_stack:
                href = self._link_stack.pop()
                if href:
                    self._para_parts.append("</a>")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._collecting_css:
            self._css_buf.append(data)
            return
        if self._in_para and data:
            self._para_parts.append(_html.escape(data))

    # ── Абзацы и недели ──────────────────────────────────────────────────

    def _close_para(self) -> None:
        if self._active_fmt:
            for f in _FMT_CLOSE_ORDER:
                if f in self._active_fmt:
                    self._para_parts.append(f"</{f}>")
            self._active_fmt = set()
        for href in reversed(self._link_stack):
            if href:
                self._para_parts.append("</a>")
        self._link_stack = []
        self._fmt_stack = []

        para_html = "".join(self._para_parts).strip()
        self._para_parts = []
        self._in_para = False

        if not para_html:
            return

        plain = _strip_invisible(re.sub(r"<[^>]+>", "", para_html))
        m = _WEEK_LINE.match(plain)
        if m:
            self._flush_current_week()
            self._current_week = int(m.group(1) or m.group(2))
            self._paragraphs = []
            self._current_banner = None
        elif self._current_week is not None:
            self._paragraphs.append(para_html)

    def _flush_current_week(self) -> None:
        if self._current_week is None:
            return
        body = "\n\n".join(self._paragraphs).strip()
        if body or self._current_banner:
            self.weeks[self._current_week] = {
                "text": body,
                "banner_url": self._current_banner,
            }
        self._current_week = None
        self._paragraphs = []
        self._current_banner = None

    def close(self) -> None:
        if self._in_para:
            self._close_para()
        self._flush_current_week()
        super().close()


def parse_weeks_from_html(html_content: str) -> Dict[int, dict]:
    """Разбирает HTML-экспорт на {номер_недели: {text: str, banner_url: str|None}}"""
    parser = _DocParser()
    parser.feed(html_content)
    parser.close()
    result = dict(sorted(parser.weeks.items()))
    if result and min(result.keys()) > 1:
        logger.warning(
            "google doc: нет недели 1, минимум=%s, ключи=%s",
            min(result.keys()),
            list(result.keys()),
        )
    return result


def build_export_url(doc_id: str) -> str:
    return f"https://docs.google.com/document/d/{doc_id.strip()}/export?format=html"


async def fetch_document_html(doc_id: str) -> str:
    """Скачивает документ как HTML (публичный доступ через «Все с ссылкой»)"""
    url = build_export_url(doc_id)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; DrMamashovBot/1.0; +https://t.me)",
        "Accept": "text/html,*/*",
    }
    timeout = aiohttp.ClientTimeout(total=45, connect=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers, allow_redirects=True) as response:
            if response.status != 200:
                body_preview = (await response.text())[:200]
                raise RuntimeError(
                    f"google doc export status={response.status}, preview={body_preview!r}"
                )
            content = await response.text()
    if not content.strip():
        logger.warning("google doc export: пустой ответ")
    return content


async def load_weeks(doc_id: str) -> Dict[int, dict]:
    """Загрузка и парсинг недель из документа"""
    raw = await fetch_document_html(doc_id)
    weeks = parse_weeks_from_html(raw)
    logger.info("google doc: распознано недель: %s", len(weeks))
    return weeks
