"""Generate WAV preview samples for each Gemini Live voice.

Output: ui/public/voice-samples/google_realtime/{voice_lower}.wav

Usage:
    pip install google-genai
    export GEMINI_API_KEY=...
    python scripts/generate_gemini_voice_samples.py

The Gemini TTS model returns raw PCM (24 kHz, 16-bit, mono), which we wrap in
a WAV header using the stdlib `wave` module.
"""

from __future__ import annotations

import os
import sys
import wave
from pathlib import Path

try:
    from google import genai
    from google.genai import types
except ImportError:
    sys.stderr.write(
        "google-genai not installed. Run: pip install google-genai\n"
    )
    sys.exit(1)

VOICES = ["Aoede", "Charon", "Fenrir", "Kore", "Leda", "Orus", "Puck", "Zephyr"]
MODEL = "gemini-2.5-flash-preview-tts"
OUTPUT_DIR = (
    Path(__file__).resolve().parent.parent
    / "ui"
    / "public"
    / "voice-samples"
    / "google_realtime"
)
SAMPLE_RATE = 24000
SAMPLE_WIDTH_BYTES = 2  # 16-bit
CHANNELS = 1


def synth_phrase(voice: str) -> str:
    return f"Hello, I'm {voice}, a voice from Google Gemini."


def write_wav(path: Path, pcm_bytes: bytes) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH_BYTES)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_bytes)


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        sys.stderr.write(
            "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set. Aborting.\n"
        )
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = genai.Client(api_key=api_key)

    for voice in VOICES:
        out_path = OUTPUT_DIR / f"{voice.lower()}.wav"
        print(f"[{voice}] generating -> {out_path.relative_to(Path.cwd()) if out_path.is_relative_to(Path.cwd()) else out_path}")

        response = client.models.generate_content(
            model=MODEL,
            contents=synth_phrase(voice),
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice,
                        ),
                    ),
                ),
            ),
        )

        pcm = response.candidates[0].content.parts[0].inline_data.data
        write_wav(out_path, pcm)
        print(f"[{voice}] wrote {out_path.stat().st_size:,} bytes")

    print(f"\nDone. {len(VOICES)} samples in {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
