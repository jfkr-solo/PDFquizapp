"""テスト用エンジン。文字数に比例した長さのビープ音を作る（APIもVOICEVOXも不要）。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .base import TTSEngine


class DummyEngine(TTSEngine):
    name = "dummy"
    ext = "wav"

    def synthesize(self, text: str, out_path: Path) -> None:
        seconds = max(0.3, len(text) * 0.02 / self.speed)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds:.2f}",
                        "-ar", "24000", "-ac", "1", str(out_path)], check=True)
