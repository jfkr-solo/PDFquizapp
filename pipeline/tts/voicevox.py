"""VOICEVOX（ローカル・無料）。VOICEVOXアプリまたは voicevox_engine を起動しておく。

  docker run --rm -p 50021:50021 voicevox/voicevox_engine:cpu-latest

環境変数 VOICEVOX_URL（既定 http://127.0.0.1:50021）。voice は話者ID（既定 3＝ずんだもん ノーマル）。
生成した音声を公開・配布する場合は、各キャラクターの利用規約に従いクレジットを表記すること。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .base import TTSEngine, TTSError


class VoicevoxEngine(TTSEngine):
    name = "voicevox"
    ext = "wav"

    def __init__(self, voice: str | None = None, speed: float = 1.0):
        super().__init__(voice or os.environ.get("VOICEVOX_SPEAKER", "3"), speed)
        self.base = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021").rstrip("/")

    def _post(self, path: str, params: dict, body: bytes | None = None) -> bytes:
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, data=body or b"", method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.URLError as e:
            raise TTSError(f"VOICEVOXに接続できません（{self.base}）。VOICEVOXを起動してください: {e}") from e

    def synthesize(self, text: str, out_path: Path) -> None:
        query = json.loads(self._post("/audio_query", {"text": text, "speaker": self.voice}))
        query["speedScale"] = self.speed
        out_path.write_bytes(self._post("/synthesis", {"speaker": self.voice}, json.dumps(query).encode()))
