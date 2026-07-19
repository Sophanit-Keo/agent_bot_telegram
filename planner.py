"""Schedule summary and daily-plan generation.

`build_summary` turns the Calendar API day payload into a concise, HTML-safe
overview of the working schedule. `generate_plan` asks the active LLM provider
for a complete morning-to-night plan (work, breaks, free time); when no LLM key
is configured (or the call fails) it falls back to a deterministic planner so
the daily digest always goes out.
"""

from __future__ import annotations

import html
import json
import logging
from datetime import date, datetime, time, timedelta
from typing import Any

import llm
from config import PROVIDER_LABELS, cfg
from i18n import tr

logger = logging.getLogger(__name__)

DAY_START = time(6, 0)
DAY_END = time(22, 30)


# -- helpers ---------------------------------------------------------------------


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _fmt_time(value: Any) -> str:
    parsed = _parse_dt(value)
    return parsed.strftime("%H:%M") if parsed else "?"


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _shift_label(work_shift: dict[str, Any]) -> str | None:
    """Human label for the work-schedule shift of the day, if any."""
    if not isinstance(work_shift, dict):
        return None
    template = work_shift.get("shift_template")
    name = None
    if isinstance(template, dict):
        name = template.get("name") or template.get("code")
    elif isinstance(template, str):
        name = template
    starts, ends = work_shift.get("starts_at"), work_shift.get("ends_at")
    if not name and not starts:
        return None
    label = str(name) if name else "Work shift"
    if starts and ends:
        label += f" {_fmt_time(starts)}-{_fmt_time(ends)}"
    if work_shift.get("blocked"):
        label += " (blocked)"
    return label


def _holiday_names(items: Any) -> list[str]:
    names = []
    for item in items or []:
        if isinstance(item, dict):
            name = item.get("name_en") or item.get("name_km") or item.get("name")
            if name:
                names.append(str(name))
    return names


def _sorted_events(day: dict[str, Any]) -> list[dict[str, Any]]:
    events = [e for e in day.get("events") or [] if isinstance(e, dict)]
    return sorted(events, key=lambda e: str(e.get("starts_at") or ""))


# -- schedule summary -----------------------------------------------------------


def build_summary(
    day: dict[str, Any],
    for_date: date,
    user_name: str | None = None,
    lang: str = "en",
) -> str:
    """Concise HTML summary of the working schedule for one day."""
    cal = day.get("calendar") or {}
    lines: list[str] = []

    weekday = cal.get("day_of_week_en") or for_date.strftime("%A")
    lines.append(f"📅 <b>{html.escape(str(weekday))}, {for_date.strftime('%d %B %Y')}</b>")
    if user_name:
        lines.append(tr(lang, "schedule_for", name=html.escape(user_name)))

    lunar_bits = [
        str(cal[key])
        for key in ("lunar_month_name", "lunar_day_name")
        if cal.get(key)
    ]
    if lunar_bits or cal.get("buddhist_era"):
        moon = str(cal.get("moon_phase") or "🌙")
        khmer = " ".join(lunar_bits)
        era = f" · BE {cal['buddhist_era']}" if cal.get("buddhist_era") else ""
        lines.append(f"{moon} {html.escape(khmer)}{era}")

    for name in ([cal["holiday"]] if cal.get("holiday") else []):
        lines.append(tr(lang, "holiday", name=html.escape(str(name))))
    for name in _holiday_names(day.get("public_holidays")):
        lines.append(tr(lang, "public_holiday", name=html.escape(name)))
    for name in _holiday_names(day.get("buddhist_events")):
        lines.append(tr(lang, "buddhist_event", name=html.escape(name)))
    for name in _holiday_names(day.get("holiday_events")):
        lines.append(tr(lang, "custom_holiday", name=html.escape(name)))
    if cal.get("is_auspicious"):
        kind = cal.get("auspicious_type")
        lines.append(tr(lang, "auspicious") + (f" ({html.escape(str(kind))})" if kind else ""))

    shift = _shift_label(day.get("work_shift") or {})
    lines.append(
        tr(lang, "working_shift", shift=html.escape(shift))
        if shift
        else tr(lang, "working_shift_none")
    )

    events = _sorted_events(day)
    lines.append("")
    if not events:
        lines.append(tr(lang, "no_events"))
    else:
        lines.append(tr(lang, "sched_header", n=len(events)))
        first_start, last_end = None, None
        busy_ranges: list[tuple[datetime, datetime]] = []
        for event in events:
            title = html.escape(str(event.get("title") or "Untitled event"))
            location = event.get("location")
            suffix = f" — 📍{html.escape(str(location))}" if location else ""
            if event.get("all_day"):
                lines.append(f"• {tr(lang, 'all_day')} — <b>{title}</b>{suffix}")
                continue
            start = _parse_dt(event.get("starts_at"))
            end = _parse_dt(event.get("ends_at"))
            span = (
                f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
                if start and end
                else (start.strftime("%H:%M") if start else "??:??")
            )
            lines.append(f"• {span} — <b>{title}</b>{suffix}")
            if start:
                first_start = min(first_start or start, start)
            if end:
                last_end = max(last_end or end, end)
                if start and end > start:
                    busy_ranges.append((start, end))
        if first_start and last_end:
            # Merge overlaps so simultaneous events are not counted twice.
            busy_minutes = 0
            if busy_ranges:
                range_start, range_end = sorted(busy_ranges, key=lambda item: item[0])[0]
                for start, end in sorted(busy_ranges, key=lambda item: item[0])[1:]:
                    if start <= range_end:
                        range_end = max(range_end, end)
                    else:
                        busy_minutes += int((range_end - range_start).total_seconds() // 60)
                        range_start, range_end = start, end
                busy_minutes += int((range_end - range_start).total_seconds() // 60)
            lines.append(
                tr(
                    lang,
                    "busy",
                    hours=f"{busy_minutes / 60:g}",
                    start=first_start.strftime("%H:%M"),
                    end=last_end.strftime("%H:%M"),
                )
            )

    notes = [n for n in day.get("notes") or [] if isinstance(n, dict) and n.get("text")]
    if notes:
        lines.append("")
        lines.append(tr(lang, "notes_header"))
        lines.extend(f"• {html.escape(str(note['text']))}" for note in notes)

    return "\n".join(lines)


# -- daily plan --------------------------------------------------------------------


def _plan_payload(day: dict[str, Any], for_date: date) -> dict[str, Any]:
    """Trimmed, LLM-friendly view of the day's calendar data."""
    cal = day.get("calendar") or {}
    return {
        "date": for_date.isoformat(),
        "weekday": cal.get("day_of_week_en") or for_date.strftime("%A"),
        "public_holidays": _holiday_names(day.get("public_holidays")),
        "buddhist_events": _holiday_names(day.get("buddhist_events")),
        "custom_holidays": _holiday_names(day.get("holiday_events")),
        "work_shift": _shift_label(day.get("work_shift") or {}),
        "events": [
            {
                "title": event.get("title"),
                "starts_at": event.get("starts_at"),
                "ends_at": event.get("ends_at"),
                "all_day": bool(event.get("all_day")),
                "location": event.get("location"),
                "description": event.get("description"),
            }
            for event in _sorted_events(day)
        ],
        "notes": [
            note.get("text")
            for note in day.get("notes") or []
            if isinstance(note, dict) and note.get("text")
        ],
    }


def day_context(day: dict[str, Any], for_date: date) -> dict[str, Any]:
    """Public, compact view of a day's calendar data for grounding AI chat."""
    return _plan_payload(day, for_date)


PLAN_SYSTEM_PROMPT = (
    "You are an intelligent personal daily planner for a user living in Cambodia "
    "(timezone: Asia/Phnom_Penh). You receive one day's calendar as JSON and "
    "create a realistic, balanced, and complete schedule from early morning until bedtime.\n\n"

    "Rules:\n"
    "- Preserve every fixed calendar event, appointment, and work shift at its exact scheduled time.\n"
    "- Fill the remaining time with a healthy, productive routine that includes:\n"
    "  • 🌅 Morning routine\n"
    "  • 🍳 Breakfast\n"
    "  • 💼 Focused work or study\n"
    "  • ☕ Short breaks\n"
    "  • 🍽️ Lunch and dinner\n"
    "  • 🚶 Exercise or a short walk when appropriate\n"
    "  • 🧘 Relaxation or personal time\n"
    "  • 📚 Learning, reading, or hobbies when time allows\n"
    "  • 🌙 Wind-down routine and sleep preparation\n"
    "- Cover the entire day, approximately 06:00 to 22:30, without leaving large unexplained gaps.\n"
    "- Keep the schedule realistic with natural transitions and reasonable break durations.\n"
    "- Output exactly one line per time block using this format:\n"
    "  HH:MM-HH:MM  <activity> <1-2 relevant emojis>\n"
    "- Use emojis naturally to make the schedule pleasant and easy to scan. Choose emojis that match the activity, for example:\n"
    "  🌅 ☀️ 🍳 ☕ 💼 💻 📚 ✍️ 🧠 🎯 🚶 🏃 💧 🍽️ 🎮 🎵 🛒 🧹 🛁 📱 😌 🌙 💤\n"
    "- Use at most 1-2 emojis per line. Do not overuse emojis.\n"
    "- Maximum 20 schedule lines.\n"
    "- After the schedule, write one short, positive motivational sentence. Address the user by name if it is provided, and include one encouraging emoji.\n"
    "- Always finish the complete day. Never stop the plan halfway.\n"
    "- Return plain text only. Do not use Markdown, headings, numbering, or bullet symbols."
)


def _fallback_plan(day: dict[str, Any], lang: str = "en") -> str:
    """Deterministic morning-to-night plan used when no LLM is available."""
    fixed: list[tuple[time, time, str]] = []
    all_day_titles: list[str] = []

    for event in _sorted_events(day):
        title = str(event.get("title") or "Event")
        if event.get("all_day"):
            all_day_titles.append(title)
            continue
        start = _parse_dt(event.get("starts_at"))
        if not start:
            continue
        end = _parse_dt(event.get("ends_at")) or (start + timedelta(hours=1))
        fixed.append((start.time(), end.time(), title))

    work_shift = day.get("work_shift") or {}
    shift_start = _parse_dt(work_shift.get("starts_at"))
    shift_end = _parse_dt(work_shift.get("ends_at"))
    if shift_start and shift_end:
        fixed.append((shift_start.time(), shift_end.time(),
                      _shift_label(work_shift) or "Work shift"))

    fixed.sort(key=lambda block: _minutes(block[0]))

    anchors = [
        (time(6, 0), time(6, 30), tr(lang, "fb_wake")),
        (time(6, 30), time(7, 0), tr(lang, "fb_breakfast")),
        (time(12, 0), time(13, 0), tr(lang, "fb_lunch")),
        (time(18, 0), time(19, 0), tr(lang, "fb_dinner")),
        (time(21, 30), time(22, 30), tr(lang, "fb_winddown")),
    ]

    def overlaps(a_start: time, a_end: time, b_start: time, b_end: time) -> bool:
        return _minutes(a_start) < _minutes(b_end) and _minutes(b_start) < _minutes(a_end)

    blocks = list(fixed)
    for anchor_start, anchor_end, label in anchors:
        if not any(overlaps(anchor_start, anchor_end, s, e) for s, e, _ in fixed):
            blocks.append((anchor_start, anchor_end, label))
    blocks.sort(key=lambda block: _minutes(block[0]))

    lines: list[str] = [
        f"{tr(lang, 'all_day')}: {title}" for title in all_day_titles
    ]
    cursor = DAY_START
    for start, end, label in blocks:
        if _minutes(start) - _minutes(cursor) >= 45:
            filler = (
                tr(lang, "fb_study")
                if _minutes(cursor) < _minutes(time(17, 0))
                else tr(lang, "fb_free")
            )
            lines.append(f"{cursor:%H:%M}-{start:%H:%M}  {filler}")
        lines.append(f"{start:%H:%M}-{end:%H:%M}  {label}")
        if _minutes(end) > _minutes(cursor):
            cursor = end
    if _minutes(DAY_END) - _minutes(cursor) >= 45:
        lines.append(f"{cursor:%H:%M}-{DAY_END:%H:%M}  {tr(lang, 'fb_free')}")
    lines.append(tr(lang, "fb_sleep"))
    lines.append(tr(lang, "fb_motto"))
    return "\n".join(lines)


async def generate_plan(
    day: dict[str, Any],
    for_date: date,
    user_name: str | None = None,
    lang: str = "en",
) -> tuple[str, str | None]:
    """Return (plan_text, source_label). source_label is the LLM provider name,
    or None when the deterministic fallback produced the plan."""
    provider = cfg.provider
    name_line = f"My name is {user_name}.\n" if user_name else ""
    lang_line = (
        "Write the whole plan in Khmer language (ភាសាខ្មែរ).\n" if lang == "km" else ""
    )
    user_message = (
        f"{name_line}{lang_line}Calendar data for {for_date.isoformat()}:\n"
        f"{json.dumps(_plan_payload(day, for_date), ensure_ascii=False, indent=2)}\n\n"
        "Create my complete daily plan."
    )
    try:
        plan = await llm.chat(
            provider,
            [{"role": "user", "content": user_message}],
            system=PLAN_SYSTEM_PROMPT,
            # Generous budget so the plan is never cut off halfway (on some
            # models internal "thinking" tokens also count against this limit).
            max_tokens=4000,
        )
        return plan.strip(), PROVIDER_LABELS[provider]
    except llm.LLMNotConfigured:
        logger.info("No API key for %s - using fallback planner", provider)
    except llm.LLMError as exc:
        logger.warning("LLM plan generation failed (%s) - using fallback planner", exc)
    return _fallback_plan(day, lang), None


async def build_digest(
    day: dict[str, Any],
    for_date: date,
    user_name: str | None = None,
    lang: str = "en",
) -> str:
    """Summary + daily plan as one HTML message for Telegram."""
    summary = build_summary(day, for_date, user_name, lang)
    plan, source = await generate_plan(day, for_date, user_name, lang)
    note = (
        tr(lang, "planned_by", source=source) if source else tr(lang, "auto_plan")
    )
    return (
        f"{summary}\n\n"
        f"{tr(lang, 'digest_plan', note=html.escape(note))}\n"
        f"{html.escape(plan)}"
    )
