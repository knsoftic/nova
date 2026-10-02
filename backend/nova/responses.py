"""User-facing response catalog. Default language is Roman Urdu; identifiers stay in English."""

from __future__ import annotations

from .ai.base import Intent

# Which phase will deliver the capability behind each not-yet-executable intent.
PENDING_CAPABILITY_PHASE = {
    "open_app": 6,
    "web_search": 8,
    "create_folder": 8,
    "system_info": 2,
    "run_workflow": 9,
}


def build_response(intent: Intent, assistant_name: str) -> str:
    e = intent.entities
    match intent.name:
        case "greeting":
            return f"Assalam-o-Alaikum! {assistant_name} online hai. Main aapki kya madad kar sakta hoon?"
        case "help":
            return (
                f"Abhi {assistant_name} Phase 1 (Foundation) mein hai. Main aapki commands samajh kar "
                "unka intent bata sakta hoon. Application kholna, search, files aur system check "
                "agle phases mein add honge."
            )
        case "open_app":
            app = e.get("app", "application")
            return (
                f"Main samajh gaya, aap {app} open karwana chahte hain. Application launch ki capability "
                f"Phase {PENDING_CAPABILITY_PHASE['open_app']} mein aayegi, is liye abhi koi action nahi kiya gaya."
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
        case "system_info":
            return (
                "Main samajh gaya, aap system ki maloomat chahte hain. System Discovery "
                f"Phase {PENDING_CAPABILITY_PHASE['system_info']} mein add hogi."
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
