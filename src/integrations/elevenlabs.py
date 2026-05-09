import io
import json
import logging
import re
import urllib.error
import urllib.request

from ..config import settings

logger = logging.getLogger(__name__)

_API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_MAX_CHARS = 2500  # keep audio files reasonable; ElevenLabs free tier has character limits


def _strip_markdown(text: str) -> str:
    """Remove Markdown formatting so the text reads naturally as speech."""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)          # **bold**
    text = re.sub(r"\*(.*?)\*", r"\1", text)               # *italic*
    text = re.sub(r"_(.*?)_", r"\1", text)                 # _italic_
    text = re.sub(r"`{1,3}.*?`{1,3}", "", text, flags=re.DOTALL)  # `code`
    text = re.sub(r"#{1,6}\s*", "", text)                  # ## headings
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)  # bullet points
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)  # [text](url)
    text = re.sub(r"\n{3,}", "\n\n", text)                 # collapse extra blank lines
    return text.strip()


def text_to_speech(text: str) -> bytes:
    """Convert text to MP3 audio bytes via the ElevenLabs API.

    Raises ValueError if credentials are not configured.
    Raises urllib.error.HTTPError on API errors.
    """
    if not settings.elevenlabs_api_key:
        raise ValueError("ELEVENLABS_API_KEY is not configured")
    if not settings.elevenlabs_voice_id:
        raise ValueError("ELEVENLABS_VOICE_ID is not configured")

    clean = _strip_markdown(text)
    if len(clean) > _MAX_CHARS:
        clean = clean[:_MAX_CHARS - 3] + "..."

    payload = json.dumps({
        "text": clean,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }).encode("utf-8")

    url = _API_URL.format(voice_id=settings.elevenlabs_voice_id)
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "xi-api-key": settings.elevenlabs_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            audio_bytes = resp.read()
        logger.info("ElevenLabs TTS: %d chars → %d bytes", len(clean), len(audio_bytes))
        return audio_bytes
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.error("ElevenLabs HTTP %d: %s", exc.code, body)
        raise
