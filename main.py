from flask import Flask, request, jsonify, render_template, send_file
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote
import asyncio
import os
import re
import tempfile
import uuid

import requests

try:
    import edge_tts
except ImportError:
    edge_tts = None

try:
    from yt_dlp import YoutubeDL
except ImportError:
    YoutubeDL = None


# =========================================================
# APP
# =========================================================

app = Flask(
    __name__,
    template_folder="templates"
)


# =========================================================
# CONFIG
# =========================================================

PORT = int(
    os.environ.get(
        "PORT",
        "5000"
    )
)

OPENROUTER_URL = (
    "https://openrouter.ai/api/v1/chat/completions"
)

OPENROUTER_MODEL = (
    "deepseek/deepseek-chat"
)

OPENROUTER_API_KEY = os.environ.get(
    "OPENROUTER_API_KEY",
    ""
).strip()


# India Standard Time
IST = timezone(
    timedelta(
        hours=5,
        minutes=30
    )
)


# Microsoft Edge Indian neural voice
TTS_VOICE = "en-IN-PrabhatNeural"


# =========================================================
# IST
# =========================================================

def get_ist_now():

    return datetime.now(
        timezone.utc
    ).astimezone(
        IST
    )


def format_ist_time():

    now = get_ist_now()

    hour = now.hour % 12 or 12

    suffix = (
        "AM"
        if now.hour < 12
        else "PM"
    )

    return (
        f"{hour}:"
        f"{now.minute:02d}:"
        f"{now.second:02d} "
        f"{suffix}"
    )


def format_ist_date():

    return get_ist_now().strftime(
        "%A, %d %B %Y"
    )


# =========================================================
# TIME DETECTION
# =========================================================

def is_time_question(text):

    text = text.lower().strip()

    phrases = [
        "what time is it",
        "what's the time",
        "whats the time",
        "current time",
        "current ist time",
        "ist time",
        "india time",
        "indian time",
        "kolkata time",
        "time in kolkata",
        "time in india",
        "tell me the time",
        "tell me current time",

        "abhi kya time hai",
        "abhi kitne baje hain",
        "abhi kitne baje hai",
        "abhi time kya hai",
        "abhi ka time kya hai",
        "time kya hai",
        "time batao",
        "time bata",
        "kitne baje hain",
        "kitne baje hai",
        "india mein kya time hai",
        "india me kya time hai",
        "kolkata mein kya time hai",
        "kolkata me kya time hai"
    ]

    if any(
        phrase in text
        for phrase in phrases
    ):
        return True

    return bool(
        re.search(
            r"\btime\b",
            text
        )
        and any(
            word in text
            for word in [
                "now",
                "current",
                "india",
                "kolkata",
                "ist",
                "abhi"
            ]
        )
    )


# =========================================================
# DATE DETECTION
# =========================================================

def is_date_question(text):

    text = text.lower().strip()

    phrases = [
        "what date is it",
        "what is today's date",
        "what's today's date",
        "today's date",
        "todays date",
        "current date",
        "today date",
        "date today",
        "what day is today",
        "which day is today",

        "aaj ki date kya hai",
        "aaj ki tarikh kya hai",
        "aaj kya date hai",
        "aaj ka din kya hai",
        "aaj ka day kya hai",
        "aaj konsa din hai",
        "aaj kaun sa din hai",
        "aaj ka date kya hai"
    ]

    return any(
        phrase in text
        for phrase in phrases
    )


# =========================================================
# DIRECT IST ANSWERS
# =========================================================

def direct_time_answer(language):

    now = get_ist_now()
    exact = format_ist_time()

    if language == "hinglish":

        if 4 <= now.hour < 12:
            part = "subah"

        elif 12 <= now.hour < 17:
            part = "dopahar"

        elif 17 <= now.hour < 21:
            part = "shaam"

        else:
            part = "raat"

        return (
            "Abhi Kolkata aur poore India mein "
            "IST ke hisaab se "
            f"{exact} ho rahe hain, "
            f"yani {part} ka time hai."
        )

    return (
        "The current time in Kolkata, India is "
        f"{exact} IST."
    )


def direct_date_answer(language):

    now = get_ist_now()

    day = now.strftime("%A")
    date = now.strftime("%d %B %Y")

    if language == "hinglish":

        return (
            f"Aaj {day} hai aur "
            f"IST ke hisaab se date "
            f"{date} hai."
        )

    return (
        f"Today is {day}, "
        f"{date} in India."
    )


# =========================================================
# NATURAL AI PROMPT
# =========================================================

def build_system_prompt(language):

    current_ist = get_ist_now().strftime(
        "%A, %d %B %Y, %I:%M:%S %p"
    )

    if language == "hinglish":

        return f"""
You are JARVIS, a friendly personal AI assistant.

Current India Standard Time:
{current_ist} IST

The user selected Hinglish.

Reply in natural everyday Indian Hinglish written in Roman script.

Sound like a normal Indian person casually talking to another person.

Use a natural mix of Hindi and English.

Examples:
haan
bilkul
dekho
acha
theek hai
samajh gaya
bata deta hoon
waise
matlab
basically
chalo
abhi
sahi hai

Do NOT sound like:
- a Hindi textbook
- a formal translator
- a news reader
- a robotic AI
- overly formal Hindi
- Sanskrit-heavy Hindi

Do not use emojis.

Do not use fake placeholders.

Do not invent live information.

Write naturally for spoken conversation.

For simple questions, answer directly.

For explanations, sound conversational and friendly.

Avoid unnecessary bullet points.
""".strip()

    return f"""
You are JARVIS, a friendly personal AI assistant.

Current India Standard Time:
{current_ist} IST

The user selected English.

Reply in natural conversational English.

Sound friendly, relaxed and natural when spoken aloud.

Do not sound robotic.

Do not use emojis.

Do not use fake placeholders.

Do not invent live information.

For simple questions, answer directly.

For explanations, be conversational and clear.

Avoid unnecessary bullet points.
""".strip()


# =========================================================
# OPENROUTER
# =========================================================

def ask_openrouter(
    prompt,
    language
):

    if not OPENROUTER_API_KEY:

        raise RuntimeError(
            "OPENROUTER_API_KEY is not configured on the server."
        )

    headers = {
        "Authorization":
            f"Bearer {OPENROUTER_API_KEY}",

        "Content-Type":
            "application/json",

        "X-Title":
            "JARVIS Web Assistant"
    }

    payload = {

        "model":
            OPENROUTER_MODEL,

        "messages": [

            {
                "role":
                    "system",

                "content":
                    build_system_prompt(
                        language
                    )
            },

            {
                "role":
                    "user",

                "content":
                    prompt
            }
        ],

        "temperature":
            0.55,

        "max_tokens":
            2500
    }

    response = requests.post(

        OPENROUTER_URL,

        headers=headers,

        json=payload,

        timeout=60
    )

    if response.status_code != 200:

        try:
            details = response.json()

        except Exception:
            details = response.text

        raise RuntimeError(
            f"OpenRouter HTTP "
            f"{response.status_code}: "
            f"{details}"
        )

    data = response.json()

    choices = data.get(
        "choices",
        []
    )

    if not choices:

        raise RuntimeError(
            "OpenRouter returned no choices."
        )

    answer = (
        choices[0]
        .get("message", {})
        .get("content", "")
    )

    if not answer:

        raise RuntimeError(
            "OpenRouter returned an empty response."
        )

    return answer.strip()


# =========================================================
# TTS CLEANING
# =========================================================

def clean_tts_text(text):

    text = str(
        text or ""
    )

    text = re.sub(
        r"```[\s\S]*?```",
        " ",
        text
    )

    text = re.sub(
        r"\[([^\]]+)\]\([^)]+\)",
        r"\1",
        text
    )

    text = re.sub(
        r"[*_#>`~|]",
        " ",
        text
    )

    text = re.sub(
        r'["“”‘’]',
        " ",
        text
    )

    text = re.sub(
        r"[\[\]\{\}]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text


# =========================================================
# NEURAL TTS
# =========================================================

async def create_tts(
    text,
    file_path
):

    communicator = edge_tts.Communicate(

        text=text,

        voice=TTS_VOICE,

        rate="-5%",

        pitch="0Hz",

        volume="+0%"
    )

    await communicator.save(
        str(file_path)
    )


@app.route(
    "/speak",
    methods=["POST"]
)
def speak():

    if edge_tts is None:

        return jsonify({
            "success": False,
            "error":
                "edge-tts is not installed on the server."
        }), 500

    data = (
        request
        .get_json(
            silent=True
        )
        or {}
    )

    text = clean_tts_text(
        data.get(
            "text",
            ""
        )
    )

    if not text:

        return jsonify({
            "success": False,
            "error":
                "Nothing to speak."
        }), 400

    file_path = (
        Path(
            tempfile.gettempdir()
        )
        /
        (
            "jarvis_"
            +
            uuid.uuid4().hex
            +
            ".mp3"
        )
    )

    try:

        asyncio.run(
            create_tts(
                text,
                file_path
            )
        )

        response = send_file(
            str(file_path),
            mimetype="audio/mpeg",
            as_attachment=False,
            download_name="jarvis.mp3"
        )

        @response.call_on_close
        def cleanup():

            try:
                file_path.unlink(
                    missing_ok=True
                )
            except Exception:
                pass

        return response

    except Exception as error:

        try:
            file_path.unlink(
                missing_ok=True
            )
        except Exception:
            pass

        return jsonify({
            "success": False,
            "error":
                f"TTS error: {error}"
        }), 500


# =========================================================
# YOUTUBE
# =========================================================

def is_music_command(text):

    text = text.lower().strip()

    actions = [
        "play",
        "bajao",
        "baja do",
        "chalao",
        "chala do",
        "sunao",
        "suna do",
        "listen to"
    ]

    music_words = [
        "song",
        "music",
        "gaana",
        "gana",
        "gaane",
        "track"
    ]

    has_action = any(
        x in text
        for x in actions
    )

    has_music = any(
        x in text
        for x in music_words
    )

    has_youtube = (
        "youtube" in text
        or
        "you tube" in text
    )

    return (
        has_action
        and
        (
            has_music
            or
            has_youtube
            or
            text.startswith("play ")
        )
    )


def extract_music_query(text):

    query = text.lower()

    patterns = [
        r"\bplay\b",
        r"\bplease\b",
        r"\bopen\b",
        r"\bwatch\b",
        r"\blisten\s+to\b",
        r"\blisten\b",
        r"\bon\s+youtube\b",
        r"\byoutube\b",
        r"\byou\s+tube\b",
        r"\b(song|music|track)\b",
        r"\b(gaana|gana|gaane)\b",
        r"\b(bajao|baja do)\b",
        r"\b(chalao|chala do)\b",
        r"\b(sunao|suna do)\b",
        r"\b(par|pe)\b"
    ]

    for pattern in patterns:

        query = re.sub(
            pattern,
            " ",
            query,
            flags=re.IGNORECASE
        )

    query = re.sub(
        r"\s+",
        " ",
        query
    ).strip()

    return query or "music"


@app.route(
    "/youtube",
    methods=["POST"]
)
def youtube():

    try:

        data = (
            request
            .get_json(
                silent=True
            )
            or {}
        )

        query = str(
            data.get(
                "query",
                ""
            )
        ).strip()

        if not query:

            return jsonify({
                "success": False,
                "error":
                    "No YouTube query."
            }), 400

        if YoutubeDL is not None:

            try:

                options = {
                    "quiet": True,
                    "no_warnings": True,
                    "skip_download": True,
                    "noplaylist": True,
                    "extract_flat": True
                }

                with YoutubeDL(
                    options
                ) as ydl:

                    result = ydl.extract_info(
                        f"ytsearch5:{query}",
                        download=False
                    )

                entries = (
                    result.get(
                        "entries",
                        []
                    )
                    if result
                    else []
                )

                if entries:

                    selected = entries[0]

                    for entry in entries:

                        title = str(
                            entry.get(
                                "title",
                                ""
                            )
                        ).lower()

                        if (
                            "official" in title
                            or
                            "lyrics" in title
                            or
                            "audio" in title
                        ):

                            selected = entry
                            break

                    video_id = selected.get(
                        "id"
                    )

                    title = (
                        selected.get(
                            "title"
                        )
                        or
                        query
                    )

                    if video_id:

                        return jsonify({

                            "success":
                                True,

                            "title":
                                title,

                            "video_id":
                                str(video_id),

                            "url":
                                (
                                    "https://www.youtube.com/watch?v="
                                    +
                                    str(video_id)
                                )
                        })

            except Exception as error:

                print(
                    "YouTube warning:",
                    repr(error)
                )

        # Fallback
        search_url = (
            "https://www.youtube.com/results"
            "?search_query="
            +
            quote(query)
        )

        return jsonify({

            "success":
                True,

            "title":
                query,

            "video_id":
                "",

            "url":
                search_url
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# ROUTES
# =========================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


@app.route("/health")
def health():

    return jsonify({

        "success":
            True,

        "message":
            "JARVIS is online",

        "api_key_loaded":
            bool(
                OPENROUTER_API_KEY
            ),

        "tts_ready":
            edge_tts is not None,

        "youtube_ready":
            YoutubeDL is not None,

        "timezone":
            "Asia/Kolkata",

        "ist_time":
            format_ist_time(),

        "ist_date":
            format_ist_date()
    })


@app.route("/ist")
def ist():

    now = get_ist_now()

    return jsonify({

        "success":
            True,

        "timezone":
            "Asia/Kolkata",

        "time":
            format_ist_time(),

        "date":
            format_ist_date(),

        "hour":
            now.hour,

        "minute":
            now.minute,

        "second":
            now.second
    })


@app.route(
    "/ask-ai",
    methods=["POST"]
)
def ask_ai():

    try:

        data = (
            request
            .get_json(
                silent=True
            )
            or {}
        )

        prompt = str(
            data.get(
                "prompt",
                ""
            )
        ).strip()

        language = str(
            data.get(
                "language",
                "english"
            )
        ).lower().strip()

        if language not in {
            "english",
            "hinglish"
        }:

            language = "english"

        if not prompt:

            return jsonify({
                "success": False,
                "error":
                    "Please enter a question."
            }), 400

        if is_time_question(
            prompt
        ):

            return jsonify({
                "success":
                    True,

                "answer":
                    direct_time_answer(
                        language
                    ),

                "source":
                    "exact_ist"
            })

        if is_date_question(
            prompt
        ):

            return jsonify({
                "success":
                    True,

                "answer":
                    direct_date_answer(
                        language
                    ),

                "source":
                    "exact_ist"
            })

        answer = ask_openrouter(
            prompt,
            language
        )

        return jsonify({
            "success":
                True,

            "answer":
                answer,

            "source":
                "openrouter"
        })

    except Exception as error:

        print(
            "AI ERROR:",
            repr(error)
        )

        return jsonify({
            "success":
                False,

            "error":
                str(error)
        }), 500


# =========================================================
# CLOUD START
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False
    )