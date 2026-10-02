"""User-facing response catalog. Default language is Roman Urdu; identifiers stay in English."""

from __future__ import annotations

from .ai.base import Intent

# Which phase will deliver the capability behind each not-yet-executable intent.
PENDING_CAPABILITY_PHASE = {
    "open_app": 6,
    "web_search": 8,
    "create_folder": 8,
    "change_setting": 7,
    "run_workflow": 9,
}


def build_response(intent: Intent, assistant_name: str) -> str:
    e = intent.entities
    match intent.name:
        case "greeting":
            return f"Assalam-o-Alaikum! {assistant_name} online hai. Main aapki kya madad kar sakta hoon?"
        case "help":
            return (
                f"Abhi {assistant_name} Phase 2 mein hai. Main aapke system ki maloomat de sakta hoon "
                "(CPU, RAM, GPU, storage, Windows, mic/speaker/camera, browsers, installed apps) aur bata sakta "
                "hoon ke koi application installed hai ya nahi. Application kholna, search aur files agle "
                "phases mein add honge."
            )
        case "change_setting":
            return (
                "Main samajh gaya, aap ek setting change karwana chahte hain. Settings change karne se pehle "
                f"Permission Engine zaroori hai jo Phase {PENDING_CAPABILITY_PHASE['change_setting']} mein aayega, "
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
