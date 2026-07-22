"""English / Khmer interface strings for the AI Telegram agent.

`tr(lang, key, **kwargs)` picks the string for a language (falls back to
English); `t(chat_id, key, **kwargs)` looks up the chat's language first.
Strings marked HTML are sent with ParseMode.HTML - placeholders substituted
into them must already be html-escaped by the caller.
"""

from __future__ import annotations

from config import cfg

LANGS = ("en", "km")

LANG_ALIASES = {
    "en": "en", "eng": "en", "english": "en",
    "km": "km", "kh": "km", "khmer": "km", "ខ្មែរ": "km",
}

STRINGS: dict[str, dict[str, str]] = {
    # -- general -------------------------------------------------------------------
    "lang_usage": {
        "en": "Usage: /language en (English) or /language km (ភាសាខ្មែរ)\nCurrent: {current}",
        "km": "របៀបប្រើ៖ /language en (English) ឬ /language km (ភាសាខ្មែរ)\nបច្ចុប្បន្ន៖ {current}",
    },
    "lang_set": {
        "en": "✅ Language set to English.",
        "km": "✅ បានប្ដូរភាសាទៅជាភាសាខ្មែរ។",
    },
    "start_greeting": {
        "en": (
            "👋 Hello! I am your AI schedule agent.\n"
            "📬 This chat receives the automatic daily digest at <b>{time}</b> "
            "(Asia/Phnom_Penh).\n\n"
        ),
        "km": (
            "👋 សួស្ដី! ខ្ញុំជាជំនួយការកាលវិភាគ AI របស់អ្នក។\n"
            "📬 ការជជែកនេះនឹងទទួលរបាយការណ៍ប្រចាំថ្ងៃដោយស្វ័យប្រវត្តិនៅម៉ោង "
            "<b>{time}</b> (ម៉ោងកម្ពុជា)។\n\n"
        ),
    },
    "signin": {
        "en": (
            "🔐 <b>Sign in to your calendar first</b>\n"
            "Before using the bot you must connect a Calendar account:\n"
            "• /login — sign in step by step (I ask email, then password)\n"
            "• /register &lt;email&gt; &lt;password&gt; [name] — create a new one\n"
            "⚠️ Do this in a private chat — I delete your messages right away."
        ),
        "km": (
            "🔐 <b>សូមចូលគណនីប្រតិទិនជាមុនសិន</b>\n"
            "មុននឹងប្រើ bot អ្នកត្រូវភ្ជាប់គណនីប្រតិទិន៖\n"
            "• /login — ចូលគណនីជាជំហានៗ (ខ្ញុំសួរអ៊ីមែល បន្ទាប់មកពាក្យសម្ងាត់)\n"
            "• /register &lt;email&gt; &lt;password&gt; [ឈ្មោះ] — បង្កើតគណនីថ្មី\n"
            "⚠️ សូមធ្វើនៅក្នុងការជជែកឯកជន — ខ្ញុំនឹងលុបសាររបស់អ្នកភ្លាមៗ។"
        ),
    },
    "help": {
        "en": (
            "🤖 <b>AI Telegram Agent</b>\n"
            "🔐 Sign-in required: /login or /register connects your calendar "
            "account — everything below works after that.\n\n"
            "<b>Calendar &amp; planning</b>\n"
            "/today [YYYY-MM-DD] — schedule summary + AI daily plan\n"
            "/tomorrow — summary + plan for tomorrow\n"
            "/yesterday — summary + plan for yesterday\n"
            "/summary [YYYY-MM-DD] — schedule summary only\n"
            "/plan [YYYY-MM-DD] — daily plan only\n"
            "/shifts [month|year|YYYY-MM|YYYY] — working-schedule list "
            "(or just ask “check my schedule this month”)\n"
            "/settime HH:MM — time of the automatic daily digest\n"
            "/stop — unsubscribe this chat from the daily digest\n\n"
            "<b>Your calendar (dynamic input)</b>\n"
            "/addevent &lt;date&gt; &lt;time&gt; &lt;title&gt; [@ place] — add an event\n"
            "/addnote [date] &lt;text&gt; — add a note\n"
            "/login — sign in to YOUR calendar account (asks email, then password)\n"
            "/cancel — cancel an interactive sign-in\n"
            "/register &lt;email&gt; &lt;password&gt; [name] — create a new account\n"
            "/account — who is signed in · /logout — sign out\n\n"
            "<b>AI chat</b>\n"
            "Just send me any text — I answer naturally and I know your calendar, "
            "so you can ask things like <i>“am I free tomorrow afternoon?”</i>\n"
            "/model — show providers · /model &lt;name&gt; — switch (gemini / claude / openai)\n"
            "/reset — clear the AI conversation history\n\n"
            "<b>Memory</b>\n"
            "I remember lasting facts you tell me in chat.\n"
            "/remember &lt;fact&gt; — save something · /memory — list · /forget &lt;n|all&gt;\n\n"
            "<b>Language</b>\n"
            "/language en — English · /language km — ភាសាខ្មែរ\n\n"
            "<b>API keys</b>\n"
            "/setkey &lt;provider&gt; &lt;key&gt; — save an API key (use in private chat!)\n"
            "/delkey &lt;provider&gt; — remove a key\n"
            "/keys — list configured keys (masked)\n"
            "/setmodel &lt;provider&gt; &lt;model&gt; — override the model id\n\n"
            "/help — show this message"
        ),
        "km": (
            "🤖 <b>ជំនួយការ AI តេឡេក្រាម</b>\n"
            "🔐 ត្រូវចូលគណនីជាមុន៖ /login ឬ /register ដើម្បីភ្ជាប់គណនីប្រតិទិន — "
            "មុខងារខាងក្រោមទាំងអស់ដំណើរការបន្ទាប់ពីនោះ។\n\n"
            "<b>ប្រតិទិន និងផែនការ</b>\n"
            "/today [YYYY-MM-DD] — សង្ខេបកាលវិភាគ + ផែនការប្រចាំថ្ងៃ AI\n"
            "/tomorrow — សម្រាប់ថ្ងៃស្អែក\n"
            "/yesterday — សម្រាប់ម្សិលមិញ\n"
            "/summary [YYYY-MM-DD] — សង្ខេបកាលវិភាគប៉ុណ្ណោះ\n"
            "/plan [YYYY-MM-DD] — ផែនការប្រចាំថ្ងៃប៉ុណ្ណោះ\n"
            "/shifts [month|year|YYYY-MM|YYYY] — បញ្ជីវេនការងារ "
            "(ឬសួរថា «កាលវិភាគការងារខែនេះ»)\n"
            "/settime HH:MM — ម៉ោងផ្ញើរបាយការណ៍ស្វ័យប្រវត្តិ\n"
            "/stop — បញ្ឈប់ការទទួលរបាយការណ៍ប្រចាំថ្ងៃ\n\n"
            "<b>ប្រតិទិនរបស់អ្នក (បញ្ចូលទិន្នន័យ)</b>\n"
            "/addevent &lt;ថ្ងៃ&gt; &lt;ម៉ោង&gt; &lt;ចំណងជើង&gt; [@ ទីកន្លែង] — បន្ថែមព្រឹត្តិការណ៍\n"
            "/addnote [ថ្ងៃ] &lt;អត្ថបទ&gt; — បន្ថែមកំណត់ចំណាំ\n"
            "/login — ចូលគណនីប្រតិទិនរបស់អ្នក (សួរអ៊ីមែល បន្ទាប់មកពាក្យសម្ងាត់)\n"
            "/cancel — បោះបង់ការចូលគណនីជាជំហានៗ\n"
            "/register &lt;email&gt; &lt;password&gt; [ឈ្មោះ] — បង្កើតគណនីថ្មី\n"
            "/account — កំពុងប្រើគណនីណា · /logout — ចាកចេញ\n\n"
            "<b>ជជែកជាមួយ AI</b>\n"
            "គ្រាន់តែផ្ញើសារធម្មតា — ខ្ញុំឆ្លើយបែបធម្មជាតិ ហើយស្គាល់ប្រតិទិនរបស់អ្នក "
            "ដូច្នេះអ្នកអាចសួរដូចជា <i>«ថ្ងៃស្អែករសៀលខ្ញុំទំនេរទេ?»</i>\n"
            "/model — បង្ហាញ ឬប្ដូរ AI (gemini / claude / openai)\n"
            "/reset — លុបប្រវត្តិសន្ទនា AI\n\n"
            "<b>ការចងចាំ</b>\n"
            "ខ្ញុំចងចាំរឿងសំខាន់ៗដែលអ្នកប្រាប់ខ្ញុំក្នុងការជជែក។\n"
            "/remember &lt;ការពិត&gt; — រក្សាទុក · /memory — បញ្ជី · /forget &lt;n|all&gt;\n\n"
            "<b>ភាសា</b>\n"
            "/language en — English · /language km — ភាសាខ្មែរ\n\n"
            "<b>សោ API</b>\n"
            "/setkey &lt;provider&gt; &lt;key&gt; — រក្សាទុកសោ API (ក្នុងការជជែកឯកជន!)\n"
            "/delkey &lt;provider&gt; — លុបសោ\n"
            "/keys — បញ្ជីសោដែលបានកំណត់\n"
            "/setmodel &lt;provider&gt; &lt;model&gt; — ប្ដូរម៉ូដែល\n\n"
            "/help — បង្ហាញជំនួយនេះ"
        ),
    },
    # -- digest / summary labels ------------------------------------------------------
    "digest_header": {
        "en": "🌅 <b>Your automatic daily digest</b>\n\n",
        "km": "🌅 <b>របាយការណ៍ប្រចាំថ្ងៃស្វ័យប្រវត្តិរបស់អ្នក</b>\n\n",
    },
    "schedule_for": {
        "en": "👤 Schedule for <b>{name}</b>",
        "km": "👤 កាលវិភាគរបស់ <b>{name}</b>",
    },
    "holiday": {"en": "🎉 Holiday: {name}", "km": "🎉 ថ្ងៃបុណ្យ៖ {name}"},
    "public_holiday": {
        "en": "🎉 Public holiday: {name}",
        "km": "🎉 ថ្ងៃឈប់សម្រាកជាតិ៖ {name}",
    },
    "buddhist_event": {
        "en": "🪷 Buddhist event: {name}",
        "km": "🪷 ពិធីបុណ្យព្រះពុទ្ធសាសនា៖ {name}",
    },
    "custom_holiday": {
        "en": "🎊 Custom holiday: {name}",
        "km": "🎊 ថ្ងៃបុណ្យផ្ទាល់ខ្លួន៖ {name}",
    },
    "auspicious": {"en": "✨ Auspicious day", "km": "✨ ថ្ងៃល្អ"},
    "working_shift": {
        "en": "👷 Working shift: {shift}",
        "km": "👷 វេនការងារ៖ {shift}",
    },
    "working_shift_none": {
        "en": "👷 Working shift: none — no work scheduled",
        "km": "👷 វេនការងារ៖ គ្មាន — មិនមានការងារត្រូវធ្វើទេ",
    },
    "login_ask_email": {
        "en": (
            "📧 Please send your calendar account <b>email</b>.\n"
            "(Your messages will be deleted right away so they never stay in "
            "the chat. Type <b>cancel</b> to stop.)"
        ),
        "km": (
            "📧 សូមផ្ញើ <b>អ៊ីមែល</b> នៃគណនីប្រតិទិនរបស់អ្នក។\n"
            "(សាររបស់អ្នកនឹងត្រូវលុបភ្លាមៗ ដើម្បីកុំឱ្យនៅសល់ក្នុងការជជែក។ "
            "វាយ <b>cancel</b> ដើម្បីបញ្ឈប់។)"
        ),
    },
    "login_ask_password": {
        "en": "🔑 Now send your <b>password</b>. It will be deleted immediately.",
        "km": "🔑 ឥឡូវសូមផ្ញើ <b>ពាក្យសម្ងាត់</b> របស់អ្នក។ វានឹងត្រូវលុបភ្លាមៗ។",
    },
    "login_bad_email": {
        "en": "⚠️ That doesn't look like an email address. Please try again (or type cancel).",
        "km": "⚠️ វាហាក់ដូចជាមិនមែនអាសយដ្ឋានអ៊ីមែលទេ។ សូមព្យាយាមម្ដងទៀត (ឬវាយ cancel)។",
    },
    "login_cancelled": {
        "en": "❌ Sign-in cancelled.",
        "km": "❌ ការចូលគណនីត្រូវបានបោះបង់។",
    },
    "login_success": {
        "en": (
            "✅ Connected calendar account <b>{email}</b>.\n"
            "This chat now sees only that account's events and notes. /logout to disconnect."
        ),
        "km": (
            "✅ បានភ្ជាប់គណនីប្រតិទិន <b>{email}</b>។\n"
            "ការជជែកនេះឃើញតែព្រឹត្តិការណ៍ និងកំណត់ចំណាំរបស់គណនីនោះប៉ុណ្ណោះ។ "
            "/logout ដើម្បីផ្ដាច់។"
        ),
    },
    "shifts_header": {
        "en": "👷 <b>Working schedule — {period}</b>\n",
        "km": "👷 <b>កាលវិភាគការងារ — {period}</b>\n",
    },
    "shifts_none": {
        "en": "👷 No working shifts scheduled for {period}.",
        "km": "👷 គ្មានវេនការងារសម្រាប់ {period} ទេ។",
    },
    "shifts_total": {
        "en": "\nTotal: <b>{n}</b> working day(s), {off} day(s) off.",
        "km": "\nសរុប៖ ថ្ងៃធ្វើការ <b>{n}</b> ថ្ងៃ, ថ្ងៃឈប់ {off} ថ្ងៃ។",
    },
    "shifts_usage": {
        "en": (
            "Usage: /shifts [month|year|YYYY-MM|YYYY]\n"
            "Examples: /shifts · /shifts month · /shifts year · "
            "/shifts 2026-08 · /shifts 2026"
        ),
        "km": (
            "របៀបប្រើ៖ /shifts [month|year|YYYY-MM|YYYY]\n"
            "ឧទាហរណ៍៖ /shifts · /shifts month · /shifts year · "
            "/shifts 2026-08 · /shifts 2026"
        ),
    },
    "sched_header": {
        "en": "🗓 <b>Schedule ({n} event(s))</b>",
        "km": "🗓 <b>កាលវិភាគ (ព្រឹត្តិការណ៍ {n})</b>",
    },
    "no_events": {
        "en": "🗓 <b>Schedule:</b> no events booked — the day is open.",
        "km": "🗓 <b>កាលវិភាគ៖</b> គ្មានព្រឹត្តិការណ៍ទេ — ថ្ងៃនេះទំនេរ។",
    },
    "all_day": {"en": "All day", "km": "ពេញមួយថ្ងៃ"},
    "busy": {
        "en": (
            "\n⏱ Busy about {hours} h between {start} and {end}; "
            "the rest of the day is free."
        ),
        "km": (
            "\n⏱ រវល់ប្រហែល {hours} ម៉ោង ចាប់ពី {start} ដល់ {end}; "
            "ពេលដែលនៅសល់គឺទំនេរ។"
        ),
    },
    "notes_header": {"en": "📝 <b>Notes</b>", "km": "📝 <b>កំណត់ចំណាំ</b>"},
    "coworkers_header": {
        "en": "👥 <b>Working with you today</b> — {shift}",
        "km": "👥 <b>អ្នកនឹងធ្វើការជាមួយថ្ងៃនេះ</b> — {shift}",
    },
    "coworkers_ungrouped": {"en": "Unassigned", "km": "មិនកំណត់ក្រុម"},
    "digest_plan": {
        "en": "🗒 <b>Daily plan</b> <i>({note})</i>",
        "km": "🗒 <b>ផែនការប្រចាំថ្ងៃ</b> <i>({note})</i>",
    },
    "plan_header": {
        "en": "🗒 <b>Daily plan for {who}{date}</b> <i>({note})</i>",
        "km": "🗒 <b>ផែនការប្រចាំថ្ងៃ {who}{date}</b> <i>({note})</i>",
    },
    "planned_by": {"en": "planned by {source}", "km": "រៀបចំដោយ {source}"},
    "auto_plan": {"en": "auto-generated plan", "km": "ផែនការបង្កើតដោយស្វ័យប្រវត្តិ"},
    # -- fallback plan blocks ------------------------------------------------------------
    "fb_wake": {
        "en": "Wake up, freshen up & light stretching",
        "km": "ក្រោកពីគេង លាងសម្អាតខ្លួន និងហាត់កាយសម្ព័ន្ធស្រាលៗ",
    },
    "fb_breakfast": {"en": "Breakfast ☕", "km": "អាហារពេលព្រឹក ☕"},
    "fb_lunch": {"en": "Lunch break 🍚", "km": "អាហារថ្ងៃត្រង់ 🍚"},
    "fb_dinner": {"en": "Dinner", "km": "អាហារពេលល្ងាច"},
    "fb_winddown": {
        "en": "Wind down, review tomorrow & relax",
        "km": "សម្រាក ពិនិត្យផែនការថ្ងៃស្អែក និងបន្ធូរអារម្មណ៍",
    },
    "fb_study": {
        "en": "Focused work / study session 📚",
        "km": "ធ្វើការ / រៀនដោយផ្ដោតអារម្មណ៍ 📚",
    },
    "fb_free": {
        "en": "Free time — rest, family, hobbies",
        "km": "ពេលទំនេរ — សម្រាក គ្រួសារ ចំណូលចិត្ត",
    },
    "fb_sleep": {
        "en": "22:30        Sleep — good night! 😴",
        "km": "22:30        គេង — រាត្រីសួស្ដី! 😴",
    },
    "fb_motto": {
        "en": "Small consistent steps win the day.",
        "km": "ជំហានតូចៗ ប្រកបដោយភាពជាប់លាប់ នាំទៅរកជោគជ័យ។",
    },
    # -- confirmations ---------------------------------------------------------------------
    "event_added": {
        "en": (
            "✅ Event added: <b>{title}</b>\n🗓 {date}, {time}{place}\n"
            "See it with /today (or /tomorrow)."
        ),
        "km": (
            "✅ បានបន្ថែមព្រឹត្តិការណ៍៖ <b>{title}</b>\n🗓 {date}, {time}{place}\n"
            "មើលវាដោយ /today (ឬ /tomorrow)។"
        ),
    },
    "note_saved": {
        "en": "📝 Note saved for {date}: {text}",
        "km": "📝 បានរក្សាទុកកំណត់ចំណាំសម្រាប់ {date}៖ {text}",
    },
}


def tr(lang: str, key: str, **kwargs) -> str:
    entry = STRINGS[key]
    template = entry.get(lang) or entry["en"]
    return template.format(**kwargs) if kwargs else template


def t(chat_id: int, key: str, **kwargs) -> str:
    return tr(cfg.get_language(chat_id), key, **kwargs)
