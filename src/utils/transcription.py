from ..config import settings

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            settings.whisper_model,
            device="cpu",
            compute_type="int8",
            download_root=settings.whisper_model_path,
        )
    return _model


def transcribe_audio(audio_path: str) -> str:
    """Transcribe an audio file (OGG/WAV/MP3) to text using Whisper."""
    model = _get_model()
    segments, _ = model.transcribe(audio_path, beam_size=5)
    return " ".join(s.text.strip() for s in segments).strip()
