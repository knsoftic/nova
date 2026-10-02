"""User-facing response catalog. Default language is Roman Urdu; identifiers stay in English."""

from __future__ import annotations

from .ai.base import Intent
from .planner import CAPABILITIES, PERMISSION_ENGINE_PHASE

# Which phase will deliver the capability behind each not-yet-executable intent.
PENDING_CAPABILITY_PHASE = {
    name: cap.available_from_phase for name, cap in CAPABILITIES.items() if cap.available_from_phase is not None
}

FALLBACK_NOTES = {
    "model_unavailable": "Local AI model abhi available nahi, is liye simple rules se samjha.",
    "timeout": "Local AI model ne waqt par jawab nahi diya, is liye simple rules se samjha.",
    "invalid_output": "Local AI model ka jawab theek nahi tha, is liye simple rules se samjha.",
    "http_error": "Ollama se rabta nahi ho saka, is liye simple rules se samjha.",
}


def build_response(intent: Intent, assistant_name: str, answer: str | None = None, user_name: str | None = None) -> str:
    e = intent.entities
    match intent.name:
        case "greeting":
            to = f" {user_name}" if user_name else ""
            return f"Assalam-o-Alaikum{to}! {assistant_name} online hai. Main aapki kya madad kar sakta hoon?"
        case "help":
            return (
                f"Main {assistant_name} hoon. Main sawalon ke jawab deta hoon, system ki maloomat batata hoon, apps "
                "kholta hoon aur windows control karta hoon, screen parhta hoon, websites kholta aur parhta hoon, web "
                "research karta hoon, files dhoondta, banata, move/copy/rename aur Recycle Bin mein bhejta hoon, folders "
                "organize karta hoon, code projects mein tests chala kar errors dhoondta aur theek karta hoon, volume, "
                "brightness aur dark mode badalta hoon, aap ke contacts ko WhatsApp/email bhejta hoon, tasveerein aur "
                "designs banata hoon, aap ke kehne par baatein yaad rakhta hoon, purani baatein dhoondta hoon aur "
                "\"work start karo\" jaise workflows yaad rakhta hoon. Khatre wale kaam se pehle hamesha ijazat leta hoon."
            )
        case "chat":
            if answer:
                return answer
            return (
                "Ye sawal samajhne ke liye local AI model chahiye jo abhi available nahi. "
                "Settings mein AI status dekhein."
            )
        case "change_setting":
            return (
                "Main samajh gaya, aap ek setting change karwana chahte hain. Settings change karne se pehle "
                f"Permission Engine zaroori hai jo Phase {PERMISSION_ENGINE_PHASE} mein aayega, "
                "is liye abhi koi setting change nahi ki gayi."
            )
        case "web_search":
            query = e.get("query")
            if not query:
                return "Aap kis cheez ki search karwana chahte hain? (Search ki capability abhi add nahi hui.)"
            return (
                f"Main samajh gaya, aap \"{query}\" ki search karwana chahte hain. Browser Agent abhi "
                "available nahi hai, is liye search nahi ki gayi."
            )
        case "create_folder":
            name = e.get("folder_name")
            target = f"\"{name}\" naam ka folder" if name else "naya folder"
            return (
                f"Main samajh gaya, aap {target} banwana chahte hain. File Agent abhi available nahi hai, "
                "is liye koi folder create nahi kiya gaya."
            )
        case _:
            return "Maaf kijiye, main ye command abhi samajh nahi saka. Dobara thore mukhtalif alfaaz mein bataiye."


def build_permission_response(intent: Intent, description: str) -> str:
    """For medium/high-risk steps, which never run before the user can grant permission."""
    e = intent.entities
    detail = {
        "type_text": f": \"{str(e.get('text', ''))[:40]}\"" if e.get("text") else "",
        "close_app": f": {e['app']}" if e.get("app") else "",
        "mouse_click": f": \"{e['target']}\"" if e.get("target") else "",
        "keyboard_shortcut": f": {e['keys']}" if e.get("keys") else "",
    }.get(intent.name, "")
    return (
        f"Ye kaam ({description}{detail}) aap ke doosre apps mein tabdeeli karta hai, is liye pehle aap ki ijazat "
        f"zaroori hai. Permission Engine Phase {PERMISSION_ENGINE_PHASE} mein aayega — tab NOVA aap se pooch kar "
        "ye karega. Abhi kuch nahi kiya gaya."
    )


def build_error_response() -> str:
    return "Maaf kijiye, command process karte waqt masla aa gaya. Detail activity log mein hai."
