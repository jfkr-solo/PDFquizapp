"""音声合成エンジンの共通インターフェース。

  engine = get_engine("voicevox")      # ローカル（無料）
  engine = get_engine("google")        # クラウド（Google Cloud Text-to-Speech）
  engine = get_engine("dummy")         # テスト用（文字数に応じた長さのビープ音）
  engine.synthesize("問題1。…", Path("out.wav"))
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path


class TTSError(Exception):
    pass


class TTSEngine(ABC):
    name: str = "base"
    ext: str = "wav"    # synthesize が書き出す形式

    def __init__(self, voice: str | None = None, speed: float = 1.0):
        if not 0.5 <= speed <= 2.0:
            raise TTSError("読み上げ速度は 0.5〜2.0 の範囲で指定してください")
        self.voice = voice
        self.speed = speed

    @abstractmethod
    def synthesize(self, text: str, out_path: Path) -> None:
        """text を音声にして out_path に保存する（形式は self.ext）。"""

    def cache_key(self) -> str:
        return f"{self.name}:{self.voice}:{self.speed}"


def get_engine(name: str, voice: str | None = None, speed: float = 1.0) -> TTSEngine:
    name = (name or os.environ.get("TTS_ENGINE", "voicevox")).lower()
    if name == "voicevox":
        from .voicevox import VoicevoxEngine
        return VoicevoxEngine(voice, speed)
    if name == "google":
        from .google import GoogleEngine
        return GoogleEngine(voice, speed)
    if name == "dummy":
        from .dummy import DummyEngine
        return DummyEngine(voice, speed)
    raise TTSError(f"不明な音声エンジンです: {name}（voicevox / google / dummy）")
