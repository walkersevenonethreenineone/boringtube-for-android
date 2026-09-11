import os
import time
import secrets
import threading
from urllib.parse import urlparse

import requests
import yt_dlp
from flask import Flask, Response, jsonify, request, stream_with_context

app = Flask(__name__)

ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*").rstrip("/")
TOKEN_TTL_SECONDS = int(os.environ.get("TOKEN_TTL_SECONDS", "14400"))  # 4 hours

_sessions = {}
_lock = threading.Lock()


def is_youtube_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        return host in {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtu.be",
            "www.youtu.be",
        }
    except Exception:
        return False


def corsify(response):
    origin = request.headers.get("Origin")
    if ALLOWED_ORIGIN == "*":
        response.headers["Access-Control-Allow-Origin"] = "*"
    elif origin == ALLOWED_ORIGIN:
        response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
        response.headers["Vary"] = "Origin"
    return response


@app.after_request
def add_headers(response):
    return corsify(response)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "BoringTube backend"})


@app.route("/api/resolve", methods=["POST", "OPTIONS"])
def resolve_video():
    if request.method == "OPTIONS":
        response = Response(status=204)
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    data = request.get_json(silent=True) or {}
    youtube_url = str(data.get("url", "")).strip()

    if not is_youtube_url(youtube_url):
        return jsonify({"error": "Нужна обычная ссылка YouTube."}), 400

    try:
        session = extract_stream(youtube_url)
    except Exception as exc:
        app.logger.exception("yt-dlp resolve failed")
        return jsonify({
            "error": "Не удалось получить видеопоток.",
            "details": str(exc)[:400]
        }), 502

    token = secrets.token_urlsafe(24)
    session["created_at"] = time.time()
    session["expires_at"] = time.time() + TOKEN_TTL_SECONDS
    session["youtube_url"] = youtube_url

    with _lock:
        cleanup_sessions_locked()
        _sessions[token] = session

    return jsonify({
        "title": session.get("title") or "Video",
        "duration": session.get("duration"),
        "format": session.get("format"),
        "stream": f"/stream/{token}"
    })


def extract_stream(youtube_url: str) -> dict:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,

        # Используем YouTube embedded client.
        # Сейчас он не требует GVS PO Token.
        "extractor_args": {
            "youtube": {
                "player_client": ["web_embedded"]
            }
        },

        # Нам нужен один уже готовый поток:
        # видео + звук вместе.
        "format": (
            "best[ext=mp4][vcodec!=none][acodec!=none]"
            "/best[vcodec!=none][acodec!=none]"
        ),
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)

    if not info:
        raise RuntimeError("yt-dlp returned no video information")

    stream_url = info.get("url")

    if not stream_url:
        raise RuntimeError("No direct media URL was returned")

    headers = dict(info.get("http_headers") or {})

    fmt = (
        info.get("format_note")
        or info.get("format")
        or info.get("format_id")
    )

    return {
        "stream_url": stream_url,
        "headers": headers,
        "title": info.get("title"),
        "duration": info.get("duration"),
        "format": fmt,
    }


def cleanup_sessions_locked():
    now = time.time()
    expired = [
        token
        for token, value in _sessions.items()
        if value.get("expires_at", 0) <= now
    ]
    for token in expired:
        _sessions.pop(token, None)


def refresh_session(token: str, current: dict) -> dict:
    refreshed = extract_stream(current["youtube_url"])
    refreshed["created_at"] = time.time()
    refreshed["expires_at"] = time.time() + TOKEN_TTL_SECONDS
    refreshed["youtube_url"] = current["youtube_url"]

    with _lock:
        _sessions[token] = refreshed

    return refreshed


@app.route("/stream/<token>", methods=["GET", "HEAD"])
def stream_video(token):
    with _lock:
        cleanup_sessions_locked()
        session = _sessions.get(token)

    if not session:
        return jsonify({"error": "Stream expired. Open the video again."}), 404

    range_header = request.headers.get("Range")

    def open_upstream(current):
        headers = dict(current.get("headers") or {})
        if range_header:
            headers["Range"] = range_header

        return requests.get(
            current["stream_url"],
            headers=headers,
            stream=True,
            timeout=(15, 60),
            allow_redirects=True,
        )

    upstream = open_upstream(session)

    if upstream.status_code in (401, 403, 410):
        upstream.close()
        try:
            session = refresh_session(token, session)
            upstream = open_upstream(session)
        except Exception:
            app.logger.exception("Could not refresh expired stream")

    passthrough_headers = {}
    for name in (
        "Content-Type",
        "Content-Length",
        "Content-Range",
        "Accept-Ranges",
        "ETag",
        "Last-Modified",
    ):
        value = upstream.headers.get(name)
        if value:
            passthrough_headers[name] = value

    passthrough_headers["Cache-Control"] = "no-store"

    if request.method == "HEAD":
        status = upstream.status_code
        upstream.close()
        return Response(status=status, headers=passthrough_headers)

    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=256 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return Response(
        stream_with_context(generate()),
        status=upstream.status_code,
        headers=passthrough_headers,
        direct_passthrough=True,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
