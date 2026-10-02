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


def build_response(intent: Intent, assistant_name: str, answer: str | None = None) -> str:
    e = intent.entities
    match intent.name:
        case "greeting":
            return f"Assalam-o-Alaikum! {assistant_name} online hai. Main aapki kya madad kar sakta hoon?"
        case "help":
            return (
                f"Main {assistant_name} hoon. Abhi main aapke sawalon ke jawab de sakta hoon, aapke system ki "
                "maloomat (CPU, RAM, GPU, storage, Windows, mic/speaker/camera, browsers, installed apps) bata "
                "sakta hoon, aur ek sath kai kaam samajh kar unka plan bana sakta hoon. Application kholna, "
                "search aur files agle phases mein add honge."
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
        case "run_workflow":
            return (
                "Main samajh gaya, aap apna work workflow start karna chahte hain. Workflow memory "
                f"Phase {PENDING_CAPABILITY_PHASE['run_workflow']} mein aayegi."
            )
        case _:
            return "Maaf kijiye, main ye command abhi samajh nahi saka. Dobara thore mukhtalif alfaaz mein bataiye."


def build_error_response() -> str:
    return "Maaf kijiye, command process karte waqt masla aa gaya. Detail activity log mein hai."
