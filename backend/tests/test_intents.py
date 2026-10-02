import asyncio

import pytest

from nova.ai.rule_based import RuleBasedProvider
from nova.language import detect_language


def detect(text):
    return asyncio.run(RuleBasedProvider().detect_intent(text))


@pytest.mark.parametrize(
    "text,intent,entities",
    [
        ("Hey NOVA, Chrome open karo.", "open_app", {"app": "Chrome"}),
        ("VS Code open karo", "open_app", {"app": "VS Code"}),
        ("WhatsApp kholo", "open_app", {"app": "WhatsApp"}),
        ("open file explorer", "open_app", {"app": "file explorer"}),
        ("کروم کھولو", "open_app", {"app": "کروم"}),
        ("क्रोम खोलो", "open_app", {"app": "क्रोम"}),
        ("Hey NOVA, mera system check karo.", "system_info", {"topic": "summary"}),
        ("Hey NOVA, mera system profile batao.", "system_info", {"topic": "summary"}),
        ("Hey NOVA, Chrome mein search karo.", "web_search", {}),
        ("Chrome mein web development search karo", "web_search", {"query": "web development"}),
        ("Open Chrome and search for web development.", "web_search", {"query": "web development"}),
        ("Hey NOVA, ye folder create karo.", "create_folder", {}),
        ("create a folder named Projects", "create_folder", {"folder_name": "Projects"}),
        ("Hey NOVA, mera work environment start karo.", "run_workflow", {"workflow": "work environment"}),
        ("Work start karo", "run_workflow", {"workflow": "work"}),
        ("Assalam-o-Alaikum", "greeting", {}),
        ("Hey NOVA", "greeting", {}),
        ("tum kya kar sakte ho", "help", {}),
        ("asdf qwerty", "unknown", {}),
    ],
)
def test_intents(text, intent, entities):
    result = detect(text)
    assert result.name == intent
    assert result.entities == entities


@pytest.mark.parametrize(
    "text,lang",
    [
        ("کروم کھولو", "ur"),
        ("क्रोम खोलो", "hi"),
        ("Chrome kholo", "roman_ur"),
        ("Chrome open karo", "mixed"),
        ("Open Chrome please", "en"),
    ],
)
def test_language(text, lang):
    assert detect_language(text) == lang
