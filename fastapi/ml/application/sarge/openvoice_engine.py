
import sys
import os
import types
from collections.abc import Iterable
import numpy as np
import torch
from loguru import logger

# Some dependency combinations (or broken numpy installs) can miss this legacy helper.
# Patch it early so downstream TTS libs don't crash on import/runtime.
if not hasattr(np, "iterable"):
    np.iterable = lambda obj: isinstance(obj, Iterable)  # type: ignore[attr-defined]

# Support both layouts:
# 1) .../openvoice_lib/openvoice
# 2) .../openvoice_lib/OpenVoice/openvoice
lib_path = os.path.join(os.path.dirname(__file__), "openvoice_lib")
openvoice_root_candidates = [
    lib_path,
    os.path.join(lib_path, "OpenVoice"),
]
for candidate in openvoice_root_candidates:
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)


def _resolve_openvoice_root() -> str:
    for candidate in openvoice_root_candidates:
        if os.path.isdir(os.path.join(candidate, "openvoice")):
            return candidate
    return lib_path


def _resolve_checkpoints_dir(openvoice_root: str) -> str:
    ckpt_candidates = [
        os.path.join(openvoice_root, "checkpoints_v2"),
        os.path.join(lib_path, "checkpoints_v2"),
        os.path.join(lib_path, "OpenVoice", "checkpoints_v2"),
    ]
    for ckpt_dir in ckpt_candidates:
        cfg = os.path.join(ckpt_dir, "converter", "config.json")
        ckpt = os.path.join(ckpt_dir, "converter", "checkpoint.pth")
        if os.path.exists(cfg) and os.path.exists(ckpt):
            return ckpt_dir
    return ckpt_candidates[0]


OPENVOICE_ROOT = _resolve_openvoice_root()

def _ensure_unidic_compat():
    """
    MeCab prefers `unidic` over `unidic_lite` when both are importable.
    In partially installed environments, `unidic` may exist but miss DICDIR,
    which breaks Melo import.
    """
    try:
        import unidic  # type: ignore
        dicdir = getattr(unidic, "DICDIR", None)
        if dicdir and os.path.exists(os.path.join(dicdir, "mecabrc")):
            return
    except Exception:
        pass

    try:
        import unidic_lite  # type: ignore
        module = sys.modules.get("unidic")
        if module is None:
            module = types.ModuleType("unidic")
            sys.modules["unidic"] = module
        module.DICDIR = unidic_lite.DICDIR
    except Exception:
        # If this fails, Melo import will raise a clear dependency error below.
        pass

def _ensure_nltk_assets():
    """
    g2p_en depends on NLTK corpora that are missing in fresh envs.
    Download lazily once to avoid runtime synthesis crashes.
    """
    resources = [
        ("taggers/averaged_perceptron_tagger_eng", "averaged_perceptron_tagger_eng"),
        ("taggers/averaged_perceptron_tagger", "averaged_perceptron_tagger"),
        ("corpora/cmudict", "cmudict"),
    ]
    try:
        import nltk  # type: ignore
        for lookup_path, package_name in resources:
            try:
                nltk.data.find(lookup_path)
            except LookupError:
                nltk.download(package_name, quiet=True)
    except Exception as e:
        logger.warning(f"TTS: NLTK asset check skipped - {e}")

_ensure_unidic_compat()

try:
    from openvoice import se_extractor
    from openvoice.api import ToneColorConverter
    from melo.api import TTS
except ImportError as e:
    searched_paths = ", ".join(openvoice_root_candidates)
    logger.error(
        f"OpenVoice: Failed to import required modules ({e}). "
        f"Searched roots: {searched_paths}"
    )
    raise

class OpenVoiceEngine:
    def __init__(self, speaker_wav=None, language="EN"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"🎙️ OpenVoice: Initializing on {self.device}")
        
        # Paths
        self.ckpt_dir = _resolve_checkpoints_dir(OPENVOICE_ROOT)
        self.converter_path = os.path.join(self.ckpt_dir, "converter")
        converter_config = os.path.join(self.converter_path, "config.json")
        converter_ckpt = os.path.join(self.converter_path, "checkpoint.pth")
        if not (os.path.exists(converter_config) and os.path.exists(converter_ckpt)):
            raise FileNotFoundError(
                "OpenVoice checkpoints not found. Expected converter files under "
                f"'{self.ckpt_dir}'. Download checkpoints_v2 and place them under "
                f"'{lib_path}/checkpoints_v2' (or '{lib_path}/OpenVoice/checkpoints_v2')."
            )
        
        # Load ToneColorConverter
        self.tone_color_converter = ToneColorConverter(
            converter_config,
            device=self.device
        )
        self.tone_color_converter.load_ckpt(converter_ckpt)
        
        # Load Base TTS (MeloTTS)
        _ensure_nltk_assets()
        self.language = language.upper()
        self.base_model = TTS(language=self.language, device=self.device)
        self.speaker_ids = self.base_model.hps.data.spk2id
        
        # Speaker Embedding
        self.speaker_wav = speaker_wav
        self.target_se = None
        if speaker_wav and os.path.exists(speaker_wav):
            self.update_speaker(speaker_wav)
        else:
            logger.warning("🎙️ OpenVoice: No speaker_wav provided or found. Cloning disabled.")

    def update_speaker(self, speaker_wav):
        logger.info(f"🎙️ OpenVoice: Processing speaker reference: {speaker_wav}")
        try:
            # Reset current embedding first. If extraction fails, cloning should be disabled explicitly.
            self.target_se = None
            # Cache embedding as .pt to avoid re-extraction
            cache_path = speaker_wav + ".se.pt"
            if os.path.exists(cache_path):
                self.target_se = torch.load(cache_path, map_location=self.device)
            else:
                self.target_se, _ = se_extractor.get_se(
                    speaker_wav, 
                    self.tone_color_converter, 
                    vad=True
                )
                torch.save(self.target_se, cache_path)
            if self.target_se is None:
                raise RuntimeError("Speaker embedding extraction returned empty result")
            logger.info("🎙️ OpenVoice: Speaker embedding cached and ready.")
        except Exception as e:
            logger.error(f"🎙️ OpenVoice: Failed to extract speaker embedding - {e}")
            raise

    def clear_speaker(self):
        """Disable cloning and use plain base voice generation."""
        self.target_se = None

    def get_default_speakers(self):
        spk_list = dict(self.speaker_ids.items()) if hasattr(self.speaker_ids, "items") else self.speaker_ids
        return sorted(list(spk_list.keys()))

    def speak(self, text, output_path, base_speaker: str | None = None):
        """
        Two-step synthesis:
        1. Base TTS (MeloTTS) -> temp.wav
        2. ToneColorConverter (OpenVoice) -> output_path
        """
        temp_wav = output_path + ".tmp.wav"
        try:
            # Step 1: Base synthesis
            # Default speaker for EN
            spk_list = dict(self.speaker_ids.items()) if hasattr(self.speaker_ids, 'items') else self.speaker_ids
            if base_speaker and base_speaker in spk_list:
                speaker_id = spk_list[base_speaker]
            else:
                speaker_id = spk_list.get(f'{self.language}-Default', 0)
            
            # MeloTTS synthesis
            self.base_model.tts_to_file(text, speaker_id, temp_wav, speed=1.0)
            
            # Step 2: Tone conversion for cloning
            if self.target_se is not None:
                # Load source embedding for the base model
                source_se_name = f'{self.language.lower()}.pth'
                if self.language == 'EN':
                    source_se_name = 'en-default.pth' # OpenVoice V2 mapping
                
                source_se_path = os.path.join(self.ckpt_dir, 'base_speakers/ses', source_se_name)
                
                if not os.path.exists(source_se_path):
                    # Fallback to en-default
                    source_se_path = os.path.join(self.ckpt_dir, 'base_speakers/ses/en-default.pth')
                
                source_se = torch.load(source_se_path, map_location=self.device)
                
                self.tone_color_converter.convert(
                    audio_src_path=temp_wav,
                    src_se=source_se,
                    tgt_se=self.target_se,
                    output_path=output_path,
                    message="@MyShell"
                )
            else:
                # Just use base synthesis if no cloning target
                if os.path.exists(temp_wav):
                    import shutil
                    shutil.move(temp_wav, output_path)
                
            logger.info(f"🎙️ OpenVoice: Synthesis complete -> {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"🎙️ OpenVoice: Synthesis failed - {e}")
            raise
        finally:
            if os.path.exists(temp_wav):
                os.remove(temp_wav)

if __name__ == "__main__":
    # Quick test
    engine = OpenVoiceEngine(speaker_wav="assets/speaker.wav")
    engine.speak("Hello, I am now using OpenVoice V2 for lightning fast and high quality synthesis.", "test_openvoice.wav")
