
from flask import Flask, render_template, request, jsonify
import subprocess
import speech_recognition as sr
import sys
import os
import re
import unicodedata
from urllib.parse import quote_plus

app = Flask(__name__)

ADB = os.environ.get("ADB_PATH", "adb")
DEVICE = os.environ.get("ANDROID_DEVICE_ID", "")
PORT = 5001

def run_adb(*args, timeout=20):
    result = subprocess.run(
        [ADB, "-s", DEVICE, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=(
            subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(error or "ADB command failed")
    return result.stdout.strip()


def check_phone():
    result = subprocess.run(
        [ADB, "devices"],
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=(
            subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
    )
    return result.returncode == 0 and any(
        len(parts := line.split()) >= 2
        and parts[0] == DEVICE
        and parts[1] == "device"
        for line in result.stdout.splitlines()
    )


def normalize(text):
    text = unicodedata.normalize("NFKC", str(text)).lower().strip()
    return " ".join(text.split())


def name_key(text):
    return " ".join(re.findall(r"[a-z0-9]+", normalize(text)))


def open_app(package):
    try:
        run_adb(
            "shell", "monkey", "-p", package,
            "-c", "android.intent.category.LAUNCHER", "1"
        )
    except RuntimeError as error:
        raise ValueError(
            f"App open nahi hua. Check karo ki app installed hai. {error}"
        ) from error


def get_contacts():
    output = run_adb(
        "shell", "content", "query",
        "--uri", "content://contacts/phones/",
        "--projection", "display_name:number"
    )

    contacts = []
    pattern = re.compile(
        r"Row:\s*\d+\s+display_name=(.*?),\s*number=(.*)$"
    )

    for line in output.splitlines():
        match = pattern.search(line.strip())
        if match:
            name = match.group(1).strip()
            number = match.group(2).strip()
            if name and number and number.lower() != "null":
                contacts.append({"name": name, "number": number})

    return contacts


def call_contact(spoken_name):
    query = name_key(spoken_name)

    if not query or query in {"me", "someone", "a number"}:
        raise ValueError("Please say a saved contact's name.")

    contacts = get_contacts()
    if not contacts:
        raise ValueError(
            "No contacts found. Check phone connection and permissions."
        )

    exact = [c for c in contacts if name_key(c["name"]) == query]

    if len(exact) == 1:
        chosen = exact[0]
    else:
        query_words = set(query.split())
        matches = []

        for contact in contacts:
            key = name_key(contact["name"])
            words = set(key.split())

            if query in key or key in query:
                score = 100 + len(query)
            else:
                score = sum(
                    10 for word in query_words
                    if len(word) >= 2
                    and any(word == w or word in w or w in word for w in words)
                )

            if score:
                matches.append((score, contact))

        if not matches:
            raise ValueError(f"No saved contact matched '{spoken_name}'.")

        matches.sort(key=lambda item: item[0], reverse=True)
        best_score = matches[0][0]
        best = {
            (c["name"], c["number"]): c
            for score, c in matches if score == best_score
        }

        if len(best) != 1:
            names = ", ".join(c["name"] for c in list(best.values())[:5])
            raise ValueError(f"Multiple contacts matched: {names}. Say a fuller name.")

        chosen = list(best.values())[0]

    run_adb(
        "shell", "am", "start",
        "-a", "android.intent.action.DIAL",
        "-d", "tel:" + chosen["number"]
    )
    return f"Dialer opened for {chosen['name']}. Confirm the call on your phone."


def get_search_request(text):
    """Return (engine, topic), or None if this is not a search command."""
    text = normalize(text)

    # Phrases that explicitly select Google.
    google_prefixes = (
        "search google for ",
        "search on google for ",
        "search on google ",
        "search google ",
        "google search for ",
        "google search ",
        "find on google ",
        "find google ",
        "google par ",
        "google pe ",
        "google mein ",
        "google me ",
    )

    for prefix in google_prefixes:
        if text.startswith(prefix):
            topic = text[len(prefix):].strip()
            return ("google", topic) if topic else None

    # Phrases that explicitly select YouTube.
    youtube_prefixes = (
        "search youtube for ",
        "search on youtube for ",
        "search youtube ",
        "youtube search for ",
        "youtube par ",
        "youtube pe ",
        "youtube mein ",
        "youtube me ",
        "find on youtube ",
        "play ",
    )

    for prefix in youtube_prefixes:
        if text.startswith(prefix):
            topic = text[len(prefix):].strip()
            return ("youtube", topic) if topic else None

    # Phrases where the engine name appears after the topic.
    suffixes = (
        (" on youtube", "youtube"),
        (" in youtube", "youtube"),
        (" youtube par", "youtube"),
        (" youtube pe", "youtube"),
        (" on google", "google"),
        (" in google", "google"),
        (" google par", "google"),
        (" google pe", "google"),
    )

    for suffix, engine in suffixes:
        if text.endswith(suffix):
            topic = text[:-len(suffix)].strip()

            for prefix in ("search ", "find ", "play "):
                if topic.startswith(prefix):
                    topic = topic[len(prefix):].strip()
                    break

            return (engine, topic) if topic else None

    # Generic "search <topic>" defaults to YouTube.
    if text.startswith("search "):
        topic = text[len("search "):].strip()
        return ("youtube", topic) if topic else None

    # Generic "find <topic>" defaults to Google.
    if text.startswith("find "):
        topic = text[len("find "):].strip()
        return ("google", topic) if topic else None

    return None



def execute_command(command):
    text = normalize(command)

    # Remove the wake word before processing the command.
    if text.startswith("jarvis "):
        text = text[len("jarvis "):].strip()
    elif text == "jarvis":
        text = ""

    print("AURA RECEIVED COMMAND:", repr(text), flush=True)


    # Handle search commands before other commands.
    search = get_search_request(text)

    if search:
        engine, query = search

        for ending in (
            " search karo", " search kar do", " search karna",
            " dhoondo", " dhundo", " please"
        ):
            if query.endswith(ending):
                query = query[:-len(ending)].strip()

        if not query:
            raise ValueError("Please say what you want to search for.")

        if engine == "youtube":
            url = (
                "https://www.youtube.com/results?search_query="
                + quote_plus(query)
            )
        else:
            url = "https://www.google.com/search?q=" + quote_plus(query)

        run_adb(
            "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", url
        )
        return f"Searching {engine.title()} for {query}."

    # Open websites/apps.
    if text in ("youtube", "open youtube", "open youtube app"):
        run_adb(
            "shell", "am", "start", "-a",
            "android.intent.action.VIEW", "-d", "https://www.youtube.com"
        )
        return "YouTube opened."

    if text in ("google", "open google", "open google app"):
        run_adb(
            "shell", "am", "start", "-a",
            "android.intent.action.VIEW", "-d", "https://www.google.com"
        )
        return "Google opened."

    if text in ("whatsapp", "open whatsapp", "launch whatsapp"):
        open_app("com.whatsapp")
        return "WhatsApp opened."

    if text in ("instagram", "open instagram", "launch instagram"):
        open_app("com.instagram.android")
        return "Instagram opened."

    # Phone navigation.
    if text in ("home", "go home", "go to home"):
        run_adb("shell", "input", "keyevent", "3")
        return "Home command sent."

    if text in ("back", "press back", "go back"):
        run_adb("shell", "input", "keyevent", "4")
        return "Back command sent."

    if text in (
        "lock", "lock phone", "lock the phone",
        "lock my phone", "turn off screen"
    ):
        run_adb("shell", "input", "keyevent", "223")
        return "Screen sleep command sent."

    if text in (
        "unlock", "unlock phone", "unlock the phone",
        "unlock my phone", "wake phone", "wake up phone"
    ):
        run_adb("shell", "input", "keyevent", "224")
        return "Screen awakened. PIN or biometrics may still be required."

    call_match = re.fullmatch(r"(?:please\s+)?call\s+(.+)", text)
    if call_match:
        return call_contact(call_match.group(1).strip())

    raise ValueError(
        "Command not supported. Try 'Search <topic>', "
        "'Search Google for <topic>', 'Search YouTube for <topic>', "
        "Open WhatsApp, Home, Back, or Call followed by a saved name."
    )


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/status")
def status():
    try:
        connected = check_phone()
        return jsonify({
            "connected": connected,
            "message": "Phone connected" if connected
            else "Phone not connected. Check USB/Wireless debugging."
        })
    except Exception as error:
        return jsonify({"connected": False, "message": str(error)}), 500


@app.route("/command", methods=["POST"])
def command():
    data = request.get_json(silent=True) or {}
    text = str(data.get("command", "")).strip()

    if not text or len(text) > 100:
        return jsonify({
            "success": False,
            "message": "Please enter a valid command."
        }), 400

    try:
        if not check_phone():
            return jsonify({
                "success": False,
                "message": "Phone disconnected. Check ADB connection."
            }), 503

        message = execute_command(text)
        return jsonify({"success": True, "message": message})

    except ValueError as error:
        return jsonify({"success": False, "message": str(error)}), 400
    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "message": "ADB timed out. Check the phone."
        }), 504
    except Exception as error:
        return jsonify({
            "success": False,
            "message": f"Command failed: {error}"
        }), 500


# Kept for compatibility with the previous dashboard.
@app.route("/listen", methods=["POST"])
def listen():
    recognizer = sr.Recognizer()

    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.listen(
                source, timeout=7, phrase_time_limit=6
            )

        spoken_text = recognizer.recognize_google(
            audio, language="en-IN"
        ).strip()

        if not spoken_text:
            raise sr.UnknownValueError()

        return jsonify({"success": True, "command": spoken_text})

    except sr.WaitTimeoutError:
        return jsonify({
            "success": False, "message": "No voice detected. Try again."
        }), 400
    except sr.UnknownValueError:
        return jsonify({
            "success": False, "message": "Voice not understood. Try again."
        }), 400
    except sr.RequestError as error:
        return jsonify({
            "success": False, "message": f"Speech network error: {error}"
        }), 502
    except Exception as error:
        return jsonify({
            "success": False, "message": f"Microphone error: {error}"
        }), 500


if __name__ == "__main__":
    print("AURA is starting...")
    print(f"Python: {sys.executable}")
    print(f"ADB device: {DEVICE}")
    print(f"Dashboard: http://127.0.0.1:{PORT}")
    app.run(host="0.0.0.0", port=PORT)
