"""STEP 9: 音声合成。エンジンは共通インターフェースで切り替える。"""
from .base import TTSEngine, TTSError, get_engine

__all__ = ["TTSEngine", "TTSError", "get_engine"]
