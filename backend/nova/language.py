"""Lightweight input-language detection (Urdu, Hindi, Roman Urdu, English, mixed)."""

from __future__ import annotations

import re

ARABIC_SCRIPT = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
WORD = re.compile(r"[a-zA-Z']+")

ROMAN_URDU_WORDS = {
    "karo", "kar", "kardo", "karein", "kijiye", "kro", "hai", "hain", "ho", "kya", "kaise", "mein", "main",
    "mera", "meri", "mere", "aap", "ap", "ye", "yeh", "wo", "woh", "batao", "bataen", "kholo", "khol",
    "chalao", "chala", "banao", "bana", "do", "dena", "nahi", "nahin", "theek", "acha", "achha", "ka",
    "ki", "ke", "ko", "se", "aur", "abhi", "kaun", "kahan", "kitna", "kitni", "salam", "assalam",
    "shukriya", "bhai", "zara", "jaldi", "sakte", "sakta", "chahiye",
}

ENGLISH_WORDS = {
    "the", "a", "an", "please", "open", "close", "search", "for", "check", "create", "show", "what",
    "is", "my", "and", "launch", "start", "tell", "me", "how", "are", "you", "can", "folder", "file",
    "status", "system", "hello", "hi", "help",
}


def detect_language(text: str) -> str:
    """Return one of: ur, hi, roman_ur, en, mixed, unknown."""
    if ARABIC_SCRIPT.search(text):
        return "ur"
    if DEVANAGARI.search(text):
        return "hi"
    words = [w.lower() for w in WORD.findall(text)]
    if not words:
        return "unknown"
    roman = sum(1 for w in words if w in ROMAN_URDU_WORDS)
    english = sum(1 for w in words if w in ENGLISH_WORDS)
    if roman and english:
        return "mixed"
    if roman:
        return "roman_ur"
    return "en"
