"""
AppleEcosystemAgent — Connecte Lucie à tout l'écosystème Apple.

Une seule instruction → actions sur Mac, iPhone, Apple Watch simultanément.
Utilise AppleScript natif + iCloud pour la synchronisation inter-appareils.
"""

import asyncio
import re
import time
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple

from pydantic.v1 import BaseModel, Field

from app.agents.base_agent import BaseAgent, Tool
from app.security.threat_intelligence import ThreatIntelligence
from app.utils.errors import ToolExecutionError
from app.utils.logger import logger
from app.utils.metrics import record_tool_execution

# Filtre anti-injection pour contenu externe (mails, messages)
_threat_filter = ThreatIntelligence()


# ─────────────────────────────────────────────────────────────────────────────
# Contrats Pydantic
# ─────────────────────────────────────────────────────────────────────────────
class CreateNoteContract(BaseModel):
    title:   str = Field("", description="Titre de la note (généré si vide)")
    content: str = Field(..., description="Contenu de la note")

class CreateReminderContract(BaseModel):
    task:       str           = Field(..., description="Description du rappel")
    minutes:    Optional[int] = Field(None, description="Dans combien de minutes")
    due_date:   Optional[str] = Field(None, description="Date/heure (format: 2026-03-15 10:00)")

class CreateEventContract(BaseModel):
    title:    str = Field(..., description="Titre de l'événement")
    date:     str = Field(..., description="Date (format: 2026-03-15)")
    time:     str = Field("09:00", description="Heure (format: HH:MM)")
    duration: int = Field(60, description="Durée en minutes")

class SendTelegramContract(BaseModel):
    message: str = Field(..., description="Message à envoyer")

class ReadMailContract(BaseModel):
    sender: Optional[str] = Field(None, description="Filtrer par expéditeur")
    count:  int           = Field(5, description="Nombre de mails à lire")

class ComposeMailContract(BaseModel):
    to:      str = Field(..., description="Destinataire")
    subject: str = Field(..., description="Sujet")
    body:    str = Field(..., description="Corps du message")

class HomeKitContract(BaseModel):
    device: str = Field(..., description="Appareil ou scène")
    action: str = Field(..., description="Action (on/off/toggle/status)")

class RunShortcutContract(BaseModel):
    name: str = Field(..., description="Nom du raccourci Apple")

class AirDropContract(BaseModel):
    filepath: str = Field(..., description="Chemin du fichier à envoyer")


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────
class AppleEcosystemAgent(BaseAgent):
    """Connecte Lucie à l'écosystème Apple : Notes, Rappels, Calendrier, Mail, Telegram, HomeKit."""

    def __init__(self, llm_service: Any, bus: Any, config: dict[str, Any]) -> None:
        super().__init__("AppleEcosystemAgent", llm_service, bus)
        self._telegram_token: Optional[str] = config.get("telegram_bot_token")
        self._telegram_chat_id: Optional[str] = config.get("telegram_chat_id")
        logger.info("🍎 AppleEcosystemAgent initialisé")

    def get_tools(self) -> list[Tool]:
        return [
            Tool(name="create_note",      description="Crée une note dans Apple Notes (sync iCloud).",   contract=CreateNoteContract),
            Tool(name="create_reminder",  description="Crée un rappel (notification Mac+iPhone+Watch).", contract=CreateReminderContract),
            Tool(name="create_event",     description="Crée un événement dans Calendrier Apple.",        contract=CreateEventContract),
            Tool(name="send_telegram",    description="Envoie un message via Telegram.",                 contract=SendTelegramContract),
            Tool(name="read_mail",        description="Lit les derniers mails dans Mail.app.",           contract=ReadMailContract),
            Tool(name="compose_mail",     description="Compose un email dans Mail.app.",                 contract=ComposeMailContract),
            Tool(name="homekit_control",  description="Contrôle un appareil HomeKit.",                   contract=HomeKitContract),
            Tool(name="run_shortcut",     description="Lance un Raccourci Apple.",                       contract=RunShortcutContract),
            Tool(name="airdrop_file",     description="Prépare un fichier pour AirDrop.",                contract=AirDropContract),
        ]

    # ── AppleScript helper ────────────────────────────────────────────────

    async def _run_applescript(self, script: str, timeout: float = 10.0) -> Tuple[bool, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode == 0:
                return True, stdout.decode().strip()
            return False, stderr.decode().strip()
        except asyncio.TimeoutError:
            return False, "Timeout"
        except Exception as e:
            return False, str(e)

    # ── Notes Apple ───────────────────────────────────────────────────────

    async def _tool_create_note(self, content: str, title: str = "") -> str:
        start = time.time()
        if not title:
            title = content[:40].replace('"', "'") + ("…" if len(content) > 40 else "")

        escaped_title = title.replace('\\', '\\\\').replace('"', '\\"')
        escaped_content = content.replace('\\', '\\\\').replace('"', '\\"')

        script = f'''
tell application "Notes"
    make new note at folder "Notes" with properties {{name:"{escaped_title}", body:"{escaped_content}"}}
end tell
'''
        success, error = await self._run_applescript(script, timeout=5.0)
        record_tool_execution(self.name, "create_note", time.time() - start, error=not success)
        if success:
            return f"✅ Note créée : \"{title}\" (sync iCloud → iPhone en ~30s)"
        raise ToolExecutionError(f"Erreur création note : {error}")

    # ── Rappels Apple ─────────────────────────────────────────────────────

    async def _tool_create_reminder(self, task: str, minutes: Optional[int] = None,
                                     due_date: Optional[str] = None) -> str:
        start = time.time()
        escaped_task = task.replace('\\', '\\\\').replace('"', '\\"')

        if minutes is not None:
            due = datetime.now() + timedelta(minutes=minutes)
            display_time = f"dans {minutes} minute{'s' if minutes > 1 else ''}"
        elif due_date:
            display_time = due_date
        else:
            # Pas de date → rappel sans échéance
            script = f'''
tell application "Reminders"
    make new reminder with properties {{name:"{escaped_task}"}}
end tell
'''
            success, error = await self._run_applescript(script, timeout=5.0)
            record_tool_execution(self.name, "create_reminder", time.time() - start, error=not success)
            if success:
                return f"✅ Rappel créé : \"{task}\" (sans échéance)"
            raise ToolExecutionError(f"Erreur rappel : {error}")

        # Avec date d'échéance
        script = f'''
tell application "Reminders"
    set dueDate to current date
    set year of dueDate to {due.year if minutes else 'year of (current date)'}
    set month of dueDate to {due.month if minutes else 'month of (current date)'}
    set day of dueDate to {due.day if minutes else 'day of (current date)'}
    set hours of dueDate to {due.hour if minutes else 0}
    set minutes of dueDate to {due.minute if minutes else 0}
    set seconds of dueDate to 0
    make new reminder with properties {{name:"{escaped_task}", due date:dueDate}}
end tell
'''
        # Si on a un due_date string, parser et construire le script
        if due_date and not minutes:
            try:
                due = datetime.strptime(due_date, "%Y-%m-%d %H:%M")
            except ValueError:
                try:
                    due = datetime.strptime(due_date, "%Y-%m-%d")
                except ValueError:
                    raise ToolExecutionError(f"Format de date invalide : {due_date}")
            script = f'''
tell application "Reminders"
    set dueDate to current date
    set year of dueDate to {due.year}
    set month of dueDate to {due.month}
    set day of dueDate to {due.day}
    set hours of dueDate to {due.hour}
    set minutes of dueDate to {due.minute}
    set seconds of dueDate to 0
    make new reminder with properties {{name:"{escaped_task}", due date:dueDate}}
end tell
'''

        success, error = await self._run_applescript(script, timeout=5.0)
        record_tool_execution(self.name, "create_reminder", time.time() - start, error=not success)
        if success:
            return f"✅ Rappel créé : \"{task}\" ({display_time}) — notification Mac + iPhone + Watch"
        raise ToolExecutionError(f"Erreur rappel : {error}")

    # ── Calendrier Apple ──────────────────────────────────────────────────

    async def _tool_create_event(self, title: str, date: str,
                                  time_str: str = "09:00", duration: int = 60) -> str:
        start = time.time()
        escaped_title = title.replace('\\', '\\\\').replace('"', '\\"')

        try:
            event_dt = datetime.strptime(f"{date} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            raise ToolExecutionError(f"Format date/heure invalide : {date} {time_str}")

        end_dt = event_dt + timedelta(minutes=duration)

        script = f'''
tell application "Calendar"
    tell calendar "Calendrier"
        set startDate to current date
        set year of startDate to {event_dt.year}
        set month of startDate to {event_dt.month}
        set day of startDate to {event_dt.day}
        set hours of startDate to {event_dt.hour}
        set minutes of startDate to {event_dt.minute}
        set seconds of startDate to 0
        set endDate to current date
        set year of endDate to {end_dt.year}
        set month of endDate to {end_dt.month}
        set day of endDate to {end_dt.day}
        set hours of endDate to {end_dt.hour}
        set minutes of endDate to {end_dt.minute}
        set seconds of endDate to 0
        make new event with properties {{summary:"{escaped_title}", start date:startDate, end date:endDate}}
    end tell
end tell
'''
        success, error = await self._run_applescript(script, timeout=5.0)
        if not success:
            # Fallback : essayer le calendrier par défaut
            script_fallback = f'''
tell application "Calendar"
    tell calendar 1
        set startDate to current date
        set year of startDate to {event_dt.year}
        set month of startDate to {event_dt.month}
        set day of startDate to {event_dt.day}
        set hours of startDate to {event_dt.hour}
        set minutes of startDate to {event_dt.minute}
        set seconds of startDate to 0
        set endDate to current date
        set year of endDate to {end_dt.year}
        set month of endDate to {end_dt.month}
        set day of endDate to {end_dt.day}
        set hours of endDate to {end_dt.hour}
        set minutes of endDate to {end_dt.minute}
        set seconds of endDate to 0
        make new event with properties {{summary:"{escaped_title}", start date:startDate, end date:endDate}}
    end tell
end tell
'''
            success, error = await self._run_applescript(script_fallback, timeout=5.0)

        record_tool_execution(self.name, "create_event", time.time() - start, error=not success)
        if success:
            return f"✅ Événement créé : \"{title}\" le {date} à {time_str} ({duration}min)"
        raise ToolExecutionError(f"Erreur calendrier : {error}")

    # ── Telegram ──────────────────────────────────────────────────────────

    async def _tool_send_telegram(self, message: str) -> str:
        start = time.time()
        if not self._telegram_token or not self._telegram_chat_id:
            return ("⚠️ Telegram non configuré. "
                    "Ajoute telegram_bot_token et telegram_chat_id dans ta config.")

        import urllib.request
        import urllib.parse
        import json

        url = (
            f"https://api.telegram.org/bot{self._telegram_token}"
            f"/sendMessage?chat_id={self._telegram_chat_id}"
            f"&text={urllib.parse.quote(message)}"
        )

        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(url, timeout=10).read()
            )
            data = json.loads(response)
            record_tool_execution(self.name, "send_telegram", time.time() - start, error=False)
            if data.get("ok"):
                return f"✅ Telegram envoyé : \"{message[:50]}…\""
            return f"⚠️ Telegram erreur : {data.get('description', 'inconnue')}"
        except Exception as e:
            record_tool_execution(self.name, "send_telegram", time.time() - start, error=True)
            raise ToolExecutionError(f"Erreur Telegram : {e}")

    # ── Mail ──────────────────────────────────────────────────────────────

    async def _tool_read_mail(self, sender: Optional[str] = None, count: int = 5) -> str:
        start = time.time()

        # Compter les mails non lus
        count_script = '''
tell application "Mail"
    set unreadCount to unread count of inbox
    return unreadCount
end tell
'''
        success, unread = await self._run_applescript(count_script, timeout=5.0)
        if not success:
            raise ToolExecutionError(f"Erreur lecture mail : {unread}")

        # Lire les derniers mails
        script = f'''
tell application "Mail"
    set output to ""
    set msgs to (messages 1 through {count} of inbox)
    repeat with m in msgs
        set subj to subject of m
        set sndr to sender of m
        set dt to date received of m
        set isRead to read status of m
        set readFlag to "📬"
        if isRead then set readFlag to "📭"
        set output to output & readFlag & " " & sndr & " | " & subj & " | " & (dt as string) & linefeed
    end repeat
    return output
end tell
'''
        success, output = await self._run_applescript(script, timeout=10.0)
        record_tool_execution(self.name, "read_mail", time.time() - start, error=not success)
        if success:
            # Filtre anti-injection sur le contenu externe
            for line in output.split("\n"):
                report = _threat_filter.analyze(line)
                if report.blocked:
                    logger.warning(f"🛡️ Contenu mail bloqué (injection détectée): {line[:60]}")
                    output = output.replace(line, "[CONTENU BLOQUÉ — injection détectée]")
            result = f"📮 {unread} mail(s) non lu(s)\n\nDerniers mails :\n{output}"
            if sender:
                lines = [line for line in output.split("\n") if sender.lower() in line.lower()]
                if lines:
                    result = f"📮 Mails de {sender} :\n" + "\n".join(lines)
                else:
                    result = f"📮 Aucun mail récent de {sender}. {unread} non lu(s) au total."
            return result
        raise ToolExecutionError(f"Erreur lecture mail : {output}")

    async def _tool_compose_mail(self, to: str, subject: str, body: str) -> str:
        start = time.time()
        to_esc = to.replace('"', '\\"')
        subject_esc = subject.replace('"', '\\"')
        body_esc = body.replace('"', '\\"').replace("\n", "\\n")

        script = f'''
tell application "Mail"
    activate
    set newMessage to make new outgoing message with properties {{subject:"{subject_esc}", content:"{body_esc}", visible:true}}
    tell newMessage
        make new to recipient at end of to recipients with properties {{address:"{to_esc}"}}
    end tell
end tell
'''
        success, error = await self._run_applescript(script, timeout=10.0)
        record_tool_execution(self.name, "compose_mail", time.time() - start, error=not success)
        if success:
            return f"✅ Mail préparé pour {to} (sujet: {subject}). Vérifie et envoie manuellement."
        raise ToolExecutionError(f"Erreur composition mail : {error}")

    # ── HomeKit ───────────────────────────────────────────────────────────

    async def _tool_homekit_control(self, device: str, action: str) -> str:
        start = time.time()
        # HomeKit via Raccourcis Apple (le moyen le plus fiable)
        shortcut_name = f"HomeKit {action} {device}"

        # Essayer d'abord via raccourci
        script = f'''
tell application "Shortcuts Events"
    run shortcut "{shortcut_name}"
end tell
'''
        success, error = await self._run_applescript(script, timeout=10.0)
        if success:
            record_tool_execution(self.name, "homekit_control", time.time() - start, error=False)
            return f"✅ HomeKit : {action} {device}"

        # Fallback : message informatif
        logger.warning(f"HomeKit non disponible pour {device}/{action}: {error}")
        record_tool_execution(self.name, "homekit_control", time.time() - start, error=True)
        return (f"⚠️ HomeKit non configuré pour \"{device}\".\n"
                f"Crée un Raccourci Apple nommé \"{shortcut_name}\" "
                f"qui contrôle cet appareil.")

    # ── Raccourcis Apple ──────────────────────────────────────────────────

    async def _tool_run_shortcut(self, name: str) -> str:
        start = time.time()
        escaped = name.replace('"', '\\"')

        script = f'''
tell application "Shortcuts Events"
    run shortcut "{escaped}"
end tell
'''
        success, error = await self._run_applescript(script, timeout=15.0)
        record_tool_execution(self.name, "run_shortcut", time.time() - start, error=not success)
        if success:
            return f"✅ Raccourci \"{name}\" exécuté."
        raise ToolExecutionError(f"Erreur raccourci : {error}")

    # ── AirDrop ───────────────────────────────────────────────────────────

    async def _tool_airdrop_file(self, filepath: str) -> str:
        start = time.time()
        import os
        expanded = os.path.expanduser(filepath)
        if not os.path.exists(expanded):
            raise ToolExecutionError(f"Fichier introuvable : {filepath}")

        # Ouvrir le panneau de partage avec AirDrop
        script = f'''
tell application "Finder"
    activate
    reveal POSIX file "{expanded}"
end tell
delay 0.5
tell application "System Events"
    tell process "Finder"
        keystroke "r" using {{command down, option down}}
    end tell
end tell
'''
        success, error = await self._run_applescript(script, timeout=5.0)
        record_tool_execution(self.name, "airdrop_file", time.time() - start, error=not success)
        if success:
            return f"✅ Fichier \"{filepath}\" prêt pour AirDrop. Choisis l'appareil cible."
        # Fallback : ouvrir Finder sur le fichier
        await self._run_applescript(f'tell application "Finder" to reveal POSIX file "{expanded}"')
        return "⚠️ Fichier ouvert dans Finder. Utilise clic droit → Partager → AirDrop."

    # ── Interface ─────────────────────────────────────────────────────────

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        kw = ["note", "rappelle", "rappel", "calendrier", "événement", "réunion",
              "lumière", "maison", "homekit", "iphone", "watch",
              "raccourci", "shortcut", "telegram", "airdrop"]
        return any(k in q for k in kw)

    async def handle(self, query: str) -> str:
        q = query.lower()

        if any(kw in q for kw in ["note", "créer une note", "crée une note"]):
            # Extraire le contenu après "note"
            content = query
            for prefix in ["crée une note qui dit ", "crée une note ", "note "]:
                if q.startswith(prefix):
                    content = query[len(prefix):]
                    break
            return await self._tool_create_note(content=content)

        if any(kw in q for kw in ["rappelle", "rappel"]):
            # Extraire la tâche et le temps
            minutes = None
            m = re.search(r"dans\s+(\d+)\s+minute", q)
            if m:
                minutes = int(m.group(1))
            task = re.sub(r"rappelle[- ]moi\s*(dans\s+\d+\s+minutes?\s*)?", "", q, flags=re.IGNORECASE).strip()
            task = re.sub(r"^(de|d'|que)\s+", "", task).strip()
            if not task:
                task = query
            return await self._tool_create_reminder(task=task, minutes=minutes)

        if any(kw in q for kw in ["calendrier", "événement", "réunion"]):
            return await self._tool_create_event(title=query, date=datetime.now().strftime("%Y-%m-%d"))

        if "telegram" in q:
            msg = re.sub(r"envoie[- ]moi\s+un\s+(?:message\s+)?telegram\s*(?:qui\s+dit\s*)?", "", q, flags=re.IGNORECASE).strip()
            if not msg:
                msg = query
            return await self._tool_send_telegram(message=msg)

        if any(kw in q for kw in ["mail non lu", "mails non lus", "combien de mail"]):
            return await self._tool_read_mail()

        if any(kw in q for kw in ["raccourci", "shortcut"]):
            name = re.sub(r"lance\s+le\s+raccourci\s+", "", q, flags=re.IGNORECASE).strip()
            return await self._tool_run_shortcut(name=name)

        if any(kw in q for kw in ["lumière", "maison", "homekit"]):
            action = "off" if any(w in q for w in ["éteins", "éteindre", "off"]) else "on"
            return await self._tool_homekit_control(device="lumières", action=action)

        if "airdrop" in q:
            filepath = re.search(r"(~/[^\s]+|/[^\s]+)", query)
            if filepath:
                return await self._tool_airdrop_file(filepath=filepath.group(1))

        return await super().handle(query)
