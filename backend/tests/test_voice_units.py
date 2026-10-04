"""Voice building blocks: wake-word detection on transcripts and speech segmentation."""

import math
from array import array

import pytest

from nova.voice.segmenter import FRAME_BYTES, Segmenter
from nova.voice.wake import detect_wake


@pytest.mark.parametrize(
    "transcript,command",
    [
        # Real Whisper outputs from NOVA's own Urdu voice saying "Hey NOVA, ...".
        ("ہی نووا، کروم کھولو۔", "کروم کھولو۔"),
        ("ہی نووا، میرا سسٹم چیک کرو۔", "میرا سسٹم چیک کرو۔"),
        ("ہی نووت اور ایم کتنی ہے۔", "اور ایم کتنی ہے۔"),  # name misheard, fuzzy match still works
        ("کی نووا، دندوز کا بیشن بتاو۔", "دندوز کا بیشن بتاو۔"),  # "Hey" misheard as "کی"
        ("کی نوول رام کتنی ہے؟", "رام کتنی ہے؟"),
        ("ہی نوور آئیم کتنی ہے۔", "آئیم کتنی ہے۔"),
        ("Hey NOVA, open Chrome", "open Chrome"),
        ("Hey Nowa what time is it", "what time is it"),
        ("नोवा, क्रोम खोलो", "क्रोम खोलो"),
        ("NOVA", ""),  # wake word only
        ("ہے نووا", ""),
        # 0.13.2: Whisper on cut-off speech splits or garbles the name.
        ("ہے نو وا، اسٹوریش چیک کرو۔", "اسٹوریش چیک کرو۔"),
        ("ہی نبہا، میرا سسٹم چیک کرو۔", "میرا سسٹم چیک کرو۔"),
    ],
)
def test_wake_detected(transcript, command):
    result = detect_wake(transcript)
    assert result.detected
    assert result.command == command


@pytest.mark.parametrize(
    "transcript",
    [
        "آج موسم بہت اچھا ہے۔",  # ordinary speech nearby: ignored
        "kal main ne nova ke baare mein suna",  # name mentioned mid-sentence, not addressed
        "Chrome kholo",
        "",
        "main nau baje aaunga",  # "nau" + next word must not make a name
        "نواب صاحب آ گئے",  # a real word close to the name is not the wake word
    ],
)
def test_wake_not_detected(transcript):
    assert not detect_wake(transcript).detected


def test_custom_wake_word():
    assert detect_wake("Suno Zara, RAM batao", assistant_name="Zara", wake_word="Suno Zara").command == "RAM batao"
    assert detect_wake("Hey Zara RAM batao", assistant_name="Zara", wake_word="Suno Zara").command == "RAM batao"
    # The old name stops working once the assistant is renamed.
    assert not detect_wake("Hey NOVA, RAM batao", assistant_name="Zara", wake_word="Suno Zara").detected


# ------------------------------------------------------------------ segmenter


def tone(ms: int, amplitude: int, freq: float = 220.0) -> bytes:
    n = 16 * ms
    return array("h", (int(amplitude * math.sin(2 * math.pi * freq * i / 16000)) for i in range(n))).tobytes()


def silence(ms: int) -> bytes:
    return bytes(32 * ms)


def feed_in_chunks(seg: Segmenter, audio: bytes, chunk: int = 3200):
    events = []
    for i in range(0, len(audio), chunk):
        events += seg.feed(audio[i:i + chunk])
    return events


def test_one_utterance_becomes_one_segment():
    events = feed_in_chunks(Segmenter(), silence(500) + tone(1200, 6000) + silence(1200))
    kinds = [k for k, _ in events]
    assert kinds == ["start", "segment"]
    seconds = len(events[1][1]) / 32000
    assert 1.2 <= seconds <= 1.9  # speech + pre-roll + a little tail


def test_two_utterances_separated_by_silence():
    audio = silence(300) + tone(800, 6000) + silence(1200) + tone(700, 6000) + silence(1200)
    assert [k for k, _ in feed_in_chunks(Segmenter(), audio)] == ["start", "segment", "start", "segment"]


def test_short_click_and_quiet_noise_ignored():
    audio = silence(300) + tone(60, 9000) + silence(1200) + tone(2000, 120) + silence(500)
    assert [k for k, _ in feed_in_chunks(Segmenter(), audio) if k == "segment"] == []


def test_long_speech_is_capped():
    events = feed_in_chunks(Segmenter(), tone(17_000, 6000) + silence(1000))
    segments = [p for k, p in events if k == "segment"]
    assert segments and len(segments[0]) / 32000 <= 15.1


def test_odd_chunk_sizes_are_buffered():
    seg = Segmenter()
    audio = silence(300) + tone(900, 6000) + silence(1200)
    events = feed_in_chunks(seg, audio, chunk=FRAME_BYTES + 7)
    assert [k for k, _ in events] == ["start", "segment"]
