"""Google Cloud Text-to-Speech（クラウド・有料）。

環境変数 GOOGLE_TTS_API_KEY（APIキー。.env に置き、Gitには入れない）。
voice は音声名（既定 ja-JP-Neural2-B）。料金は文字数課金なので、生成済みの音声はキャッシュして再利用する。
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .base import TTSEngine, TTSError

ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
MAX_BYTES = 4800  # 1リクエストの上限（5000バイト）に余裕を持たせる


class GoogleEngine(TTSEngine):
    name = "google"
    ext = "mp3"

    def __init__(self, voice: str | None = None, speed: float = 1.0):
        super().__init__(voice or os.environ.get("GOOGLE_TTS_VOICE", "ja-JP-Neural2-B"), speed)
        self.key = os.environ.get("GOOGLE_TTS_API_KEY", "").strip()
        if not self.key:
            raise TTSError("環境変数 GOOGLE_TTS_API_KEY が設定されていません")

    def synthesize(self, text: str, out_path: Path) -> None:
        if len(text.encode()) > MAX_BYTES:
            raise TTSError(f"文章が長すぎます（{len(text.encode())}バイト）。解説を分けてください")
        body = {
            "input": {"text": text},
            "voice": {"languageCode": "ja-JP", "name": self.voice},
            "audioConfig": {"audioEncoding": "MP3", "speakingRate": self.speed},
        }
        # キーはURLに載せずヘッダーで送る（アクセスログに残さない）
        req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": self.key})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise TTSError(f"Google TTS がエラーを返しました（HTTP {e.code}）: {e.read().decode(errors='replace')[:200]}") from e
        except urllib.error.URLError as e:
            raise TTSError(f"Google TTS に接続できません: {e.reason}") from e
        out_path.write_bytes(base64.b64decode(data["audioContent"]))
