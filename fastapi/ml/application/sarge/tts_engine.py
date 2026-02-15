import os
from pathlib import Path
from typing import Any

import soundfile as sf
import torch
from loguru import logger
from qwen_tts import Qwen3TTSModel


DEFAULT_QWEN_TTS_MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"


def _resolve_dtype() -> torch.dtype:
    if torch.cuda.is_available():
        if torch.cuda.is_bf16_supported():
            return torch.bfloat16
        return torch.float16
    return torch.float32


class XTTSEngine:
    """
    Backwards-compatible TTS engine wrapper, now powered by Qwen3-TTS 0.6B Base.
    """

    def __init__(self, speaker_wav: str | None = None, language: str = "en"):
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.dtype = _resolve_dtype()
        self.language = os.getenv("QWEN_TTS_LANGUAGE", "Auto")
        self.model_name = os.getenv("QWEN_TTS_MODEL", DEFAULT_QWEN_TTS_MODEL)
        self.max_new_tokens = int(os.getenv("QWEN_TTS_MAX_NEW_TOKENS", "1024"))

        logger.info(
            "TTS: Loading Qwen3-TTS model '{}' on {} (dtype={})",
            self.model_name,
            self.device,
            str(self.dtype).replace("torch.", ""),
        )
        self.model = Qwen3TTSModel.from_pretrained(
            self.model_name,
            device_map=self.device,
            dtype=self.dtype,
        )

        self.default_speaker_wav = (
            str(Path(speaker_wav)) if speaker_wav and Path(speaker_wav).exists() else None
        )
        self.default_voice_prompt: Any = None
        self.voice_clone_prompt: Any = None
        self.active_speaker_wav: str | None = None

        if self.default_speaker_wav:
            self.default_voice_prompt = self._create_voice_prompt(self.default_speaker_wav)
            self.voice_clone_prompt = self.default_voice_prompt
            self.active_speaker_wav = self.default_speaker_wav
        else:
            logger.warning(
                "TTS: No default speaker wav available. Voice cloning requires a profile upload."
            )

    def _create_voice_prompt(self, speaker_wav: str):
        if not Path(speaker_wav).exists():
            raise FileNotFoundError(f"Speaker wav not found: {speaker_wav}")
        return self.model.create_voice_clone_prompt(
            ref_audio=speaker_wav,
            ref_text=None,
            x_vector_only_mode=True,
        )

    def ensure_speaker(self, speaker_wav: str | None):
        if not speaker_wav:
            return

        speaker_wav = str(Path(speaker_wav))
        if speaker_wav == self.active_speaker_wav and self.voice_clone_prompt is not None:
            return

        if speaker_wav == self.default_speaker_wav and self.default_voice_prompt is not None:
            self.voice_clone_prompt = self.default_voice_prompt
            self.active_speaker_wav = speaker_wav
            return

        self.voice_clone_prompt = self._create_voice_prompt(speaker_wav)
        self.active_speaker_wav = speaker_wav

    def update_speaker(self, speaker_wav: str):
        self.ensure_speaker(speaker_wav)

    def clear_speaker(self):
        # Restore to startup/default speaker profile if present.
        if self.default_voice_prompt is not None:
            self.voice_clone_prompt = self.default_voice_prompt
            self.active_speaker_wav = self.default_speaker_wav
        else:
            self.voice_clone_prompt = None
            self.active_speaker_wav = None

    def get_default_speakers(self):
        # This model is clone-first; expose one stable default option for UI compatibility.
        return ["Qwen3-Base-Clone"]

    def speak(self, text, output_path, base_speaker: str | None = None):
        del base_speaker  # Not used by Qwen3-TTS base clone mode.

        if not text or not str(text).strip():
            raise ValueError("Text is required for TTS synthesis")

        if self.voice_clone_prompt is None:
            raise RuntimeError(
                "No voice clone prompt loaded. Upload a voice profile first."
            )

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        wavs, sample_rate = self.model.generate_voice_clone(
            text=str(text)[:1000],
            language=self.language,
            voice_clone_prompt=self.voice_clone_prompt,
            non_streaming_mode=True,
            max_new_tokens=self.max_new_tokens,
        )
        if not wavs:
            raise RuntimeError("Qwen3-TTS returned empty audio output")

        sf.write(str(output_file), wavs[0], sample_rate)
        logger.info("TTS: Qwen3 synthesis complete -> {}", output_file)
        return str(output_file)

    def tts_to_file(self, text, file_path, speaker_wav=None, language="en-us"):
        del language  # Kept for interface compatibility.
        self.ensure_speaker(speaker_wav)
        return self.speak(text, file_path)
