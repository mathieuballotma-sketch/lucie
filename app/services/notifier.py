from __future__ import annotations
import logging
import subprocess
import time

logger = logging.getLogger(__name__)

async def generate_notification_text(context: str) -> str:
    try:
        import aiohttp
        prompt = (
            f"Tu es Lucie, assistante IA locale. "
            f"Genere UNE notification courte (max 12 mots) "
            f"en francais pour : {context}. "
            f"Ton : amical, direct. Pas de guillemets ni apostrophes."
        )
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "http://localhost:11434/api/generate",
                json={"model":"qwen2.5:3b","prompt":prompt,"stream":False},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    text = data.get("response","").strip()
                    text = text.replace('"','').replace("'","").replace("\n"," ")
                    return text[:80].split(".")[0]
    except Exception as e:
        logger.warning(f"Ollama indisponible : {e}")
    return context[:80]

def send_notification(title: str, message: str, subtitle: str = "") -> bool:
    # Nettoie les caracteres speciaux pour AppleScript
    message = message.replace('"','').replace("\\","").replace("'","")
    title   = title.replace('"','').replace("'","")
    subtitle = subtitle.replace('"','').replace("'","")
    sub = f'subtitle "{subtitle}"' if subtitle else ""
    script = f'display notification "{message}" with title "{title}" {sub}'
    try:
        subprocess.run(["osascript","-e",script], check=True, timeout=5)
        return True
    except Exception as e:
        logger.error(f"Erreur notification : {e}")
        return False

async def lucie_notify(context: str, title: str = "Lucie") -> bool:
    t0 = time.perf_counter()
    message = await generate_notification_text(context)
    ms = (time.perf_counter() - t0) * 1000
    print(f"  Texte genere en {ms:.0f}ms : {message}")
    return send_notification(title, message, subtitle="agent_lucide")
