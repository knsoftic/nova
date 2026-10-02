"""Roman Urdu -> Urdu script conversion used for the Urdu voice."""

import ast
import pathlib
import re

import pytest

from nova.voice.translit import LEXICON, prepare_for_speech, to_urdu_script

ARABIC = re.compile(r"[؀-ۿ]")


@pytest.mark.parametrize(
    "roman,urdu",
    [
        ("Chrome khul gaya hai.", "Chrome کھل گیا ہے."),
        ("Main ne aapki file update kar di hai.", "میں نے آپ کی file update کر دی ہے."),
        ("Ye action karne ke liye aapki permission chahiye.", "یہ action کرنے کے لیے آپ کی permission چاہیے."),
        ("Assalam-o-Alaikum! NOVA online hai.", "السلام علیکم! NOVA online ہے."),
        ("RAM: total 31 GB hai", "RAM: total 31 GB ہے"),
    ],
)
def test_sentences(roman, urdu):
    assert to_urdu_script(roman) == urdu


def test_english_words_and_names_stay_latin():
    out = to_urdu_script("Visual Studio Code is PC par installed hai")
    assert "Visual Studio Code" in out and "installed" in out and "PC" in out
    assert "پر" in out and "ہے" in out


def test_fallback_only_for_words_that_look_urdu():
    out = to_urdu_script("aap samjhayenge")  # unknown word with a clear Urdu ending
    assert ARABIC.search(out.split()[1])
    assert to_urdu_script("Firefox") == "Firefox"


def test_existing_urdu_script_untouched():
    assert to_urdu_script("کروم کھولو") == "کروم کھولو"


def test_long_replies_are_shortened_for_speech():
    from nova.voice.tts import MAX_SPEECH_CHARS, REST_ON_SCREEN, shorten_for_speech

    long = "۔ ".join(["یہ ایک لمبی رپورٹ کا جملہ ہے"] * 30)
    out = shorten_for_speech(long)
    assert len(out) <= MAX_SPEECH_CHARS + len(REST_ON_SCREEN)
    assert out.endswith(REST_ON_SCREEN)
    assert shorten_for_speech("چھوٹا جواب۔") == "چھوٹا جواب۔"


def test_prepare_for_speech_removes_symbols():
    out = prepare_for_speech("Aapne 2 kaam bataye:\n1. RAM: 16 GB free / 31 GB (48% use)\n2. Step → done")
    assert "/" not in out and "→" not in out and "%" not in out and "\n" not in out
    assert "فیصد" in out and "میں سے" in out


# Words in NOVA's own reply templates that are English on purpose (read as English by the voice).
ENGLISH_OK = set("""
a account action actions activity add administrator adobe agent agents ai all an and answers application
applications apps are at availability available below brain browser browsers build camera can capabilities
capability catalog change changing check choose chrome claim code come command connected cores cpu create
default detail detect display does edge elevated engine english execute executed exist facing failed fallback
far file files folder free from gb google gpu handling here how identifiers in installed intent intents into it
known language launch levels live local log low memory mic microphone microsoft mode model most ms need network
never non normal not note nova o of off ollama on online only open or orchestrator ordered otherwise output pc
permission phase phases photoshop plan planned planner plug primary process processor profile questions ram read
receive report reported response responses returned rights risk risky roman rules run s scan search setting
settings simple so speaker standard start state stats status stay step steps storage studio system task test
text that the threads total turns type understand understood urdu usage use user verification version visual
web which whose window windows work workflow yet alaikum assalam found returns
afterwards arranging assume before but click computer control focusing grant high info its keyboard medium mouse
opening plugs reading screen screenshot shortcut spec success tab verified verify buttons tabs clipboard
command select cut paste redo undo refresh enter escape minimize maximize normal size desktop focus launch
exactly text typed for access arrange current every fake goes load name nothing ocr real reports resolve save
second shortcuts substitute switch tests this through update was taskbar
affect after again allow always answer anything app applies apply approval approvals approve approved as ask asked
asking asks audit broader button by bypasses cancel card chose classification context counts covered covers decision
deny did directly don't earlier field first go ha happen happens link made needs newest no nope ok okay overwrite
password per planner's please plz question raise remembered request requires resolved runs said same section set
shown spoken stop terminal timeout title trail treat unless unsaved user's using what when where within without
would yeah yep yes be
""".split())


def test_every_template_word_is_covered():
    """New Roman Urdu words in replies must be added to the lexicon, or the voice mispronounces them."""
    root = pathlib.Path(__file__).resolve().parent.parent / "nova"
    missing = set()
    for f in ["responses.py", "agents/system_agent.py", "agents/computer.py", "orchestrator.py", "planner.py",
              "permissions/engine.py"]:
        tree = ast.parse((root / f).read_text(encoding="utf-8"))
        # Docstrings are developer documentation, never spoken.
        docstrings = {
            id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if id(node) in docstrings:
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and " " in node.value:
                for w in re.findall(r"[A-Za-z']+", node.value):
                    if w.lower() not in LEXICON and w.lower() not in ENGLISH_OK:
                        missing.add(w.lower())
    assert not missing, f"Add to LEXICON (Urdu) or ENGLISH_OK: {sorted(missing)}"
