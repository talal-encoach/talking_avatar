#!/usr/bin/env python3
"""Check keys in keys.local.env. Prints status only, never the key."""

import json
import urllib.error
import urllib.request
from pathlib import Path

ENV_PATH = Path(__file__).with_name("keys.local.env")


def load_env(path):
    values = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("'\"")
    return values


def redact(text, secrets):
    cleaned = text
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


def request(url, headers, secrets, data=None):
    payload = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
            if content_type.startswith("audio/") or content_type.startswith("application/octet-stream"):
                return response.status, f"audio {len(raw)} bytes"
            return response.status, raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        return error.code, redact(body, secrets)
    except Exception as error:
        return None, redact(str(error), secrets)


def short_error(body):
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return " ".join(body.split())[:180]
    error = payload.get("error", payload)
    if isinstance(error, dict):
        message = error.get("message") or error.get("status") or str(error)
    else:
        message = str(error)
    return " ".join(str(message).split())[:180]


def check_openai(key):
    status, body = request(
        "https://api.openai.com/v1/models",
        {"Authorization": f"Bearer {key}"},
        [key],
    )
    if status != 200:
        return False, f"HTTP {status}: {short_error(body)}"
    models = {item.get("id") for item in json.loads(body).get("data", [])}
    needed = "gpt-4.1-mini"
    if needed in models:
        return True, f"accepted, {needed} is available"
    return True, f"accepted, but {needed} is not listed on this key"


def check_google(key):
    status, body = request(
        "https://eu-texttospeech.googleapis.com/v1/voices?languageCode=en-GB",
        {"X-Goog-Api-Key": key},
        [key],
    )
    if status != 200:
        return False, f"HTTP {status}: {short_error(body)}"
    count = len(json.loads(body).get("voices", []))
    return True, f"accepted, {count} en-GB voices"


def check_elevenlabs(key):
    # TalkingHead speaks over the text-to-speech API. A key can do that
    # without permission to read the account, so test speech directly.
    status, body = request(
        "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM?output_format=pcm_22050",
        {"xi-api-key": key, "Content-Type": "application/json"},
        [key],
        {"text": "Hi", "model_id": "eleven_turbo_v2_5"},
    )
    if status != 200:
        return False, f"HTTP {status}: {short_error(body)}"
    return True, f"accepted, speech returned ({body})"


CHECKS = [
    ("OPENAI_API_KEY", check_openai),
    ("GOOGLE_TTS_API_KEY", check_google),
    ("ELEVENLABS_API_KEY", check_elevenlabs),
]


def main():
    if not ENV_PATH.exists():
        print(f"Missing {ENV_PATH.name}")
        return 1
    values = load_env(ENV_PATH)
    failed = False
    for name, check in CHECKS:
        key = values.get(name, "")
        if not key:
            print(f"{name}: not set")
            continue
        try:
            ok, detail = check(key)
        except Exception as error:
            ok, detail = False, redact(str(error), [key])
        print(f"{name}: {'working' if ok else 'not working'} ({detail})")
        failed = failed or not ok
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
