"""Self-configuration: derive settings and component suggestions from the detected hardware.

Only runtime settings are applied automatically. Models/engines are suggested, never installed.
"""

from __future__ import annotations

from .models import Recommendation, SystemProfile

GB = 1024**3


def recommend(profile: SystemProfile) -> list[Recommendation]:
    ram_gb = (profile.ram_total_bytes or 0) / GB
    threads = profile.cpu.threads or 0
    dedicated = [g for g in profile.gpus if g.dedicated]
    vram_gb = max(((g.memory_bytes or 0) / GB for g in dedicated), default=0.0)
    has_cuda = any(g.vendor == "nvidia" for g in dedicated)
    recs: list[Recommendation] = []

    if has_cuda:
        device, device_reason = "cuda", f"NVIDIA GPU ({vram_gb:.0f} GB VRAM) mila, is liye AI GPU par chalega."
    elif dedicated:
        device, device_reason = "gpu_experimental", "Dedicated non-NVIDIA GPU mila; GPU support engine par depend karega, CPU fallback rahega."
    else:
        device, device_reason = "cpu", "Dedicated GPU nahi mila (sirf integrated graphics), is liye AI CPU par chalega."
    recs.append(Recommendation(key="compute_device", value=device, reason=device_reason, auto_applied=True))

    if vram_gb >= 12 and ram_gb >= 32:
        tier, reason = "large", "Zyada VRAM aur RAM hai — bara local model (~14B parameters) GPU par chal sakta hai."
    elif vram_gb >= 6 and ram_gb >= 16:
        tier, reason = "medium", "Achhi GPU aur RAM hai — medium local model (~7-8B parameters) GPU par chal sakta hai."
    elif ram_gb >= 15:
        tier = "small"
        reason = f"{ram_gb:.0f} GB RAM aur GPU nahi — chhota model (~3-4B parameters) CPU par tez chalega."
        if ram_gb >= 30 and threads >= 8:
            reason += " 7-8B model bhi chal sakta hai lekin jawab slow honge."
    elif ram_gb >= 7:
        tier, reason = "tiny", f"{ram_gb:.0f} GB RAM — sirf bohat chhota model (~1-2B parameters) munasib hai."
    else:
        tier, reason = "rule_based_only", "RAM kam hai — local LLM ki bajaye rule-based brain behtar rahega."
    recs.append(Recommendation(key="ai_model_tier", value=tier, reason=reason + " (Install Phase 4 mein aapki marzi se hoga.)"))

    if has_cuda:
        stt, stt_reason = "faster-whisper medium (cuda, float16)", "GPU par Whisper medium tez aur accurate rahega."
    elif threads >= 8:
        stt, stt_reason = "faster-whisper small (cpu, int8)", f"{threads} CPU threads — Whisper small CPU par theek chalega."
    else:
        stt, stt_reason = "faster-whisper base (cpu, int8)", "CPU kam taqatwar hai — Whisper base model behtar rahega."
    recs.append(Recommendation(key="stt_model", value=stt, reason=stt_reason + " (Phase 5 mein.)"))

    multi = len(profile.displays) > 1
    recs.append(
        Recommendation(
            key="multi_monitor_awareness",
            value="enabled" if multi else "disabled",
            reason=f"{len(profile.displays)} display mila." if profile.displays else "Display detect nahi hua.",
            auto_applied=True,
        )
    )

    recs.append(
        Recommendation(
            key="voice_input",
            value="available" if profile.microphones else "unavailable",
            reason=f"Microphone mila: {profile.microphones[0].name}" if profile.microphones else "Koi active microphone nahi mila.",
            auto_applied=True,
        )
    )
    recs.append(
        Recommendation(
            key="voice_output",
            value="available" if profile.speakers else "unavailable",
            reason=f"Speaker mila: {profile.speakers[0].name}" if profile.speakers else "Koi active speaker nahi mila.",
            auto_applied=True,
        )
    )
    return recs
