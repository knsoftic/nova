"""Energy-based voice activity segmentation for a 16 kHz mono int16 stream.

Cuts the continuous microphone stream into utterances: speech starts after a short run of loud
frames, ends after a stretch of silence. The noise floor adapts, so a quiet room and a noisy one
both work. Whisper's own VAD filter cleans each segment again before transcription.
"""

from __future__ import annotations

from array import array
from collections import deque
from dataclasses import dataclass, field
from math import sqrt

SAMPLE_RATE = 16_000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
FRAME_BYTES = FRAME_SAMPLES * 2


def frame_rms(frame: bytes) -> float:
    samples = array("h", frame)
    if not samples:
        return 0.0
    return sqrt(sum(s * s for s in samples) / len(samples))


@dataclass
class SegmenterConfig:
    start_ms: int = 150  # loud audio needed to start a segment
    end_silence_ms: int = 600  # silence that ends a segment (shorter = a faster reply)
    max_ms: int = 15_000  # hard cap per utterance
    min_speech_ms: int = 300  # shorter blips (clicks, coughs) are dropped
    pre_roll_ms: int = 500  # audio kept from before speech started, so first syllables ("Hey") are not cut
    threshold_ratio: float = 3.0  # speech must be this many times louder than the noise floor
    min_rms: float = 250.0  # absolute floor (int16 scale) so near-silence never counts as speech


@dataclass
class Segmenter:
    config: SegmenterConfig = field(default_factory=SegmenterConfig)
    noise_floor: float = 150.0

    def __post_init__(self) -> None:
        c = self.config
        self._start_frames = max(1, c.start_ms // FRAME_MS)
        self._end_frames = max(1, c.end_silence_ms // FRAME_MS)
        self._max_frames = c.max_ms // FRAME_MS
        self._min_frames = c.min_speech_ms // FRAME_MS
        self._pre_roll: deque[bytes] = deque(maxlen=max(1, c.pre_roll_ms // FRAME_MS))
        self._pending = b""
        self.reset()

    def reset(self) -> None:
        self._in_speech = False
        self._loud_run = 0
        self._silence_run = 0
        self._speech_frames = 0
        self._frames: list[bytes] = []
        self._pre_roll.clear()

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def _is_loud(self, rms: float) -> bool:
        return rms > max(self.config.min_rms, self.noise_floor * self.config.threshold_ratio)

    def feed(self, pcm: bytes) -> list[tuple[str, bytes]]:
        """Returns events: ("start", b"") when speech begins, ("segment", pcm) when an utterance ends."""
        events: list[tuple[str, bytes]] = []
        data = self._pending + pcm
        usable = len(data) - len(data) % FRAME_BYTES
        self._pending = data[usable:]
        for offset in range(0, usable, FRAME_BYTES):
            frame = data[offset:offset + FRAME_BYTES]
            rms = frame_rms(frame)
            loud = self._is_loud(rms)
            if not self._in_speech:
                if not loud:
                    # Adapt to the room only while nobody is speaking.
                    self.noise_floor = 0.95 * self.noise_floor + 0.05 * rms
                self._pre_roll.append(frame)
                self._loud_run = self._loud_run + 1 if loud else 0
                if self._loud_run >= self._start_frames:
                    self._in_speech = True
                    self._frames = list(self._pre_roll)
                    self._speech_frames = self._loud_run
                    self._silence_run = 0
                    events.append(("start", b""))
                continue

            self._frames.append(frame)
            if loud:
                self._speech_frames += 1
                self._silence_run = 0
            else:
                self._silence_run += 1
            if self._silence_run >= self._end_frames or len(self._frames) >= self._max_frames:
                if self._speech_frames >= self._min_frames:
                    # Drop most of the trailing silence; keep a little so the last word is not clipped.
                    keep = len(self._frames) - max(0, self._silence_run - 5)
                    events.append(("segment", b"".join(self._frames[:keep])))
                self.reset()
        return events
