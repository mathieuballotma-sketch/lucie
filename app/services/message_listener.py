from __future__ import annotations
import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)
CHAT_DB = Path.home() / "Library/Messages/chat.db"

# Commandes reconnues
COMMANDS = {
    "synthese":   "knowledge_agent",
    "resume":     "knowledge_agent",
    "note":       "apple_ecosystem",
    "ouvre":      "computer_control",
    "ferme":      "computer_control",
    "rappel":     "reminder",
    "ecris":      "creator",
    "redige":     "creator",
    "analyse":    "knowledge_agent",
    "lucie":      "ping",
}

class MessageListener:
    """
    Ecoute les nouveaux iMessages en temps reel.
    Detecte les commandes et les execute via Lucie.
    """

    def __init__(self) -> None:
        self._last_rowid: int = self._get_last_rowid()
        self._running: bool = False
        self._handlers: list[Callable[..., Any]] = []
        logger.info(f"MessageListener init — dernier message : {self._last_rowid}")

    def on_command(self, handler: Callable[..., Any]) -> None:
        """Enregistre un handler appele a chaque nouvelle commande."""
        self._handlers.append(handler)

    async def start(self) -> None:
        """Demarre l'ecoute en boucle."""
        self._running = True
        logger.info("Lucie ecoute les iMessages...")
        print("Lucie ecoute les iMessages — envoie-toi un message depuis iPhone")
        while self._running:
            await self._check_new_messages()
            await asyncio.sleep(2)  # Poll toutes les 2s

    def stop(self) -> None:
        self._running = False

    async def _check_new_messages(self) -> None:
        try:
            conn = sqlite3.connect(
                f"file:{CHAT_DB}?mode=ro", uri=True,
                check_same_thread=False,
                timeout=2.0,
            )
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT m.rowid, m.text, m.is_from_me, m.date
                FROM message m
                WHERE m.rowid > ?
                AND m.text IS NOT NULL
                AND m.text != ''
                ORDER BY m.rowid ASC
                """,
                (self._last_rowid,)
            )
            rows = cursor.fetchall()
            conn.close()

            for rowid, text, is_from_me, date in rows:
                self._last_rowid = rowid
                if is_from_me:
                    # Ignore les reponses de Lucie
                    if text.strip().startswith("Lucie :"):
                        continue
                    await self._process_command(text.strip())

        except Exception as e:
            logger.debug(f"Erreur lecture chat.db : {e}")

    async def _process_command(self, text: str) -> None:
        """Detecte et execute une commande."""
        text_lower = text.lower()

        # Detection du type de commande
        agent = None
        for keyword, ag in COMMANDS.items():
            if keyword in text_lower:
                agent = ag
                break

        if agent is None:
            # Pas une commande reconnue — ignore
            return

        logger.info(f"Commande detectee : '{text[:50]}' → {agent}")
        print(f"Commande : '{text[:60]}' → {agent}")

        # Execute la commande
        response = await self._execute(text, agent)

        # Repond via iMessage a toi-meme
        await self._reply(response)

    async def _execute(self, command: str, agent: str) -> str:
        """Execute la commande via le bon agent."""
        try:
            if agent == "ping":
                return "Lucie operationnelle — prete a recevoir tes commandes"

            if agent == "knowledge_agent":
                return await self._handle_knowledge(command)

            if agent == "apple_ecosystem":
                return await self._handle_note(command)

            if agent == "computer_control":
                from app.brain.cortex.router import PathRouter
                router = PathRouter()
                router.initialize()
                result = router.route(command)
                return f"Commande executee : {result.agent} ({result.confidence:.0%})"

            if agent == "reminder":
                return await self._handle_reminder(command)

            if agent == "creator":
                return await self._handle_creator(command)

            return f"Commande '{command[:30]}' recue — traitement en cours"

        except Exception as e:
            logger.error(f"Erreur execution : {e}")
            return f"Erreur : {str(e)[:80]}"

    async def _handle_knowledge(self, command: str) -> str:
        """Synthese via LLM + creation de note."""
        try:
            import aiohttp
            prompt = (
                f"Commande recue : {command}\n"
                f"Reponds en 3-4 lignes max en francais. "
                f"Si on te demande une synthese, fais-la brievement."
            )
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    "http://localhost:11434/api/generate",
                    json={"model":"gemma2:9b","prompt":prompt,"stream":False},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        result = data.get("response","").strip()[:300]
                        # Cree aussi une note Apple
                        await self._create_note("Synthese Lucie", result)
                        return f"Synthese creee + note Apple :\n{result[:150]}"
        except Exception as e:
            return f"Erreur synthese : {e}"
        return "Synthese impossible"

    async def _handle_note(self, command: str) -> str:
        """Cree une note Apple."""
        content = command.replace("note","").replace("Note","").strip()
        await self._create_note("Lucie", content or command)
        return f"Note creee : {content[:50]}"

    async def _handle_reminder(self, command: str) -> str:
        """Cree un rappel."""
        safe_cmd = command[:80].replace('"', '').replace("'", "").replace("\\", "")
        script = f'''
        tell application "Reminders"
            tell list "Reminders"
                set r to make new reminder
                set name of r to "{safe_cmd}"
                set due date of r to ((current date) + 3600)
            end tell
        end tell
        '''
        proc = await asyncio.create_subprocess_exec(
            "osascript","-e",script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return f"Rappel cree : {command[:50]}"

    async def _handle_creator(self, command: str) -> str:
        """Generation de contenu via LLM."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    "http://localhost:11434/api/generate",
                    json={"model":"gemma2:9b","prompt":command,"stream":False},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        return str(data.get("response","")).strip()[:300]
        except Exception as e:
            return f"Erreur LLM : {e}"
        return "Generation impossible"

    async def _create_note(self, title: str, content: str) -> None:
        """Cree une note Apple."""
        content = content.replace('"','').replace("'","").replace("\\","")
        title = title.replace('"','').replace("'","")
        script = f'''
        tell application "Notes"
            tell account "iCloud"
                make new note with properties {{name:"{title}", body:"{content}"}}
            end tell
        end tell
        '''
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript","-e",script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except Exception as e:
            logger.error(f"Erreur note : {e}")

    async def _reply(self, message: str) -> None:
        """Repond via iMessage a toi-meme."""
        msg = ("Lucie : " + message).replace('"','').replace("'","")[:200]
        # Envoie a ton propre numero
        script = f'''
        tell application "Messages"
            set s to first service whose service type = iMessage
            set b to buddy (handle of (first account of s)) of s
            send "{msg}" to b
        end tell
        '''
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript","-e",script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10.0)
            logger.info(f"Reponse envoyee : {msg[:40]}")
        except Exception as e:
            logger.error(f"Erreur reply : {e}")

    def _get_last_rowid(self) -> int:
        """Recupere le dernier rowid connu."""
        try:
            conn = sqlite3.connect(
                f"file:{CHAT_DB}?mode=ro", uri=True,
                check_same_thread=False, timeout=2.0,
            )
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(rowid) FROM message")
            result = cursor.fetchone()
            conn.close()
            return result[0] or 0
        except Exception:
            return 0
