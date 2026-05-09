import logging
import re

logger = logging.getLogger(__name__)

_VOICE_NAME = "en-US-Neural2-D"
_LANGUAGE_CODE = "en-US"
_MAX_CHARS = 4500  # Google TTS limit is 5000 bytes; stay safely under


def _strip_markdown(text: str) -> str:
    """Remove Markdown formatting so the text reads naturally as speech."""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)                    # **bold**
    text = re.sub(r"\*(.*?)\*", r"\1", text)                         # *italic*
    text = re.sub(r"_(.*?)_", r"\1", text)                           # _italic_
    text = re.sub(r"`{1,3}.*?`{1,3}", "", text, flags=re.DOTALL)     # `code`
    text = re.sub(r"#{1,6}\s*", "", text)                             # ## headings
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)     # bullet points
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)            # [text](url)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _build_client():
    from google.cloud import texttospeech
    from .google_auth import get_credentials
    creds = get_credentials()
    return texttospeech.TextToSpeechClient(credentials=creds)


def text_to_speech(text: str) -> bytes:
    """Convert text to MP3 audio bytes using Google Cloud Text-to-Speech."""
    from google.cloud import texttospeech

    clean = _strip_markdown(text)
    if len(clean) > _MAX_CHARS:
        clean = clean[:_MAX_CHARS - 3] + "..."

    client = _build_client()
    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=clean),
        voice=texttospeech.VoiceSelectionParams(
            language_code=_LANGUAGE_CODE,
            name=_VOICE_NAME,
        ),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
        ),
    )
    logger.info("Google TTS: %d chars → %d bytes", len(clean), len(response.audio_content))
    return response.audio_content


def probe() -> None:
    """Lightweight check — list voices to verify the API is enabled."""
    from google.cloud import texttospeech
    client = _build_client()
    client.list_voices(request=texttospeech.ListVoicesRequest(language_code="en-US"))
