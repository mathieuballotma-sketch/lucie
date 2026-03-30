"""
SmartMailAgent — Traite les mails un par un.

Chaque mail est analysé individuellement par LLM :
classification → action → résumé.

Connecté à : CalendarAgent, AppleEcosystemAgent, VoiceManager.
"""

import asyncio
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from pydantic.v1 import BaseModel, Field

from app.agents.base_agent import BaseAgent, Tool
from app.security.threat_intelligence import ThreatIntelligence
from app.utils.errors import ToolExecutionError
from app.utils.logger import logger

# Filtre anti-injection pour contenu mail externe
_threat_filter = ThreatIntelligence()


# ── Contrats Pydantic ────────────────────────────────────────────────────────

class ProcessInboxContract(BaseModel):
    limit: int = Field(5, description="Nombre de mails à traiter")

class AnalyzeSingleMailContract(BaseModel):
    sender: str = Field(..., description="Expéditeur du mail")
    subject: str = Field(..., description="Sujet du mail")
    body: str = Field("", description="Corps du mail (extrait)")

class WatchInboxContract(BaseModel):
    interval: int = Field(300, description="Intervalle de vérification en secondes")

class ReplyMailContract(BaseModel):
    subject: str = Field("", description="Sujet du mail auquel répondre")
    sender: str = Field("", description="Expéditeur du mail")
    content: str = Field("", description="Contenu de la réponse (vide = suggestion auto)")

class ComposeMailContract(BaseModel):
    to: str = Field("", description="Destinataire")
    subject: str = Field("", description="Sujet du mail")
    content: str = Field("", description="Contenu du mail (vide = génération auto)")

class ConfirmMailContract(BaseModel):
    action: str = Field("confirm", description="confirm ou cancel")


# ── Prompt de classification ─────────────────────────────────────────────────

_CLASSIFICATION_PROMPT = """Analyse ce mail et réponds UNIQUEMENT en JSON :
{{
  "type": "spam|pub|pro|urgent|personnel",
  "priorite": 1-5,
  "resume": "1 phrase max",
  "action": "ignorer|lire|repondre|urgent",
  "contient_reunion": true/false,
  "contient_deadline": true/false
}}

Expéditeur : {sender}
Sujet : {subject}
Corps : {body}"""


# ── Agent ────────────────────────────────────────────────────────────────────

class SmartMailAgent(BaseAgent):
    """
    Traite les mails un par un.
    Chaque mail est analysé individuellement par LLM.
    """

    def __init__(self, llm_service: Any, bus: Any, config: Dict[str, Any]) -> None:
        super().__init__("SmartMailAgent", llm_service, bus)
        self.stability = "core"  # Agent prioritaire — cas d'usage principal avocats
        self._watch_task: Optional[asyncio.Task[None]] = None
        self._last_unread: int = 0
        # Référence au registre injectée par le cortex
        self._registry: Optional[Any] = None
        # Sémaphore : max 3 appels Ollama simultanés pour éviter la saturation
        self._ollama_sem: asyncio.Semaphore = asyncio.Semaphore(3)
        # État des actions mail en attente de confirmation
        self._pending_reply: Optional[Dict[str, Any]] = None
        self._pending_compose: Optional[Dict[str, Any]] = None
        logger.info("📧 SmartMailAgent initialisé")

    def get_tools(self) -> List[Tool]:
        return [
            Tool(
                name="process_inbox",
                description="Traite les mails non lus un par un : analyse, classe, agit",
                contract=ProcessInboxContract,
            ),
            Tool(
                name="analyze_single_mail",
                description="Analyse un seul mail : type, priorité, actions",
                contract=AnalyzeSingleMailContract,
            ),
            Tool(
                name="watch_inbox",
                description="Surveille l'inbox en continu, notifie les mails importants",
                contract=WatchInboxContract,
            ),
            Tool(
                name="reply_mail",
                description="Prépare une réponse à un mail (aperçu avant envoi)",
                contract=ReplyMailContract,
            ),
            Tool(
                name="compose_mail",
                description="Compose un nouveau mail (aperçu avant envoi)",
                contract=ComposeMailContract,
            ),
            Tool(
                name="confirm_mail",
                description="Confirme ou annule l'envoi du mail en attente",
                contract=ConfirmMailContract,
            ),
        ]

    def can_handle(self, query: str) -> bool:
        q = query.lower()
        kw = [
            "mail", "mails", "email", "emails", "inbox",
            "boîte mail", "boite mail", "courrier",
            "traite mes mail", "classe mes mail",
            "mails non lus", "nouveau mail",
            "réponds", "répondre", "réponse",
            "reply", "envoie une réponse",
            "répond au mail", "répond à ce mail",
            "écris un mail", "compose un mail", "compose",
            "confirme", "annule",
        ]
        return any(k in q for k in kw)

    async def handle(self, query: str) -> str:
        """Routage par intention."""
        q = query.lower()
        # Confirme/annule en priorité absolue
        if any(kw in q for kw in ["confirme", "oui", "ok envoie", "valide"]):
            return await self._tool_confirm_mail(action="confirm")
        if any(kw in q for kw in ["annule", "non", "abandonne", "cancel"]):
            return await self._tool_confirm_mail(action="cancel")
        # Compose un nouveau mail
        if any(kw in q for kw in ["écris un mail", "compose un mail", "compose", "nouveau mail à"]):
            return await self._tool_compose_mail()
        # Répondre à un mail
        if any(kw in q for kw in ["réponds", "répondre", "réponse au mail", "reply", "répond au mail"]):
            subject = self._extract_subject_from_query(query)
            return await self._tool_reply_mail(subject=subject)
        if any(kw in q for kw in ["surveille", "watch", "monitore"]):
            return await self._tool_watch_inbox()
        if any(kw in q for kw in ["classe", "trie", "organise"]):
            return await self._tool_process_inbox(limit=20)
        # Défaut : traiter l'inbox
        return await self._tool_process_inbox()

    def _extract_subject_from_query(self, query: str) -> str:
        """Extrait le sujet du mail depuis la query utilisateur."""
        patterns = [
            r'mail[^"]*["\']([^"\']+)["\']',
            r'sujet[^"]*["\']([^"\']+)["\']',
            r'à propos de (.+)',
        ]
        for p in patterns:
            m = re.search(p, query.lower())
            if m:
                return m.group(1).strip()
        # Fallback : dernier mail urgent en cache
        if hasattr(self, "_last_urgent_subject"):
            return self._last_urgent_subject
        return ""

    # ── AppleScript helper ───────────────────────────────────────────────

    async def _run_applescript(self, script: str, timeout: float = 10.0) -> Tuple[bool, str]:
        """Exécute un AppleScript avec timeout."""
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

    def _sanitize(self, text: str) -> str:
        """Filtre anti-injection sur contenu mail externe."""
        safe = []
        for line in text.split("\n"):
            report = _threat_filter.analyze(line)
            if report.blocked:
                logger.warning(f"🛡️ Contenu mail bloqué: {line[:60]}")
                safe.append("[CONTENU BLOQUÉ]")
            else:
                safe.append(line)
        return "\n".join(safe)

    # ── Lecture mails via AppleScript ─────────────────────────────────────

    async def _fetch_unread_mails(self, limit: int = 10) -> List[Dict[str, str]]:
        """Lit les N derniers mails de l'inbox (rapide, sans corps)."""
        # Lecture rapide des N premiers messages (pas de filtre 'whose' — trop lent sur inbox volumineuse)
        script = f'''
tell application "Mail"
    set output to ""
    set msgs to (messages 1 through {limit} of inbox)
    repeat with m in msgs
        set sndr to sender of m
        set subj to subject of m
        set dt to date received of m as string
        set isUnread to not (read status of m)
        if isUnread then
            set output to output & sndr & "|||" & subj & "|||" & dt & linefeed
        end if
    end repeat
    return output
end tell
'''
        ok, raw = await self._run_applescript(script, timeout=10.0)
        if not ok:
            raise ToolExecutionError(f"Erreur lecture mails : {raw}")

        raw = self._sanitize(raw)
        mails = []
        seen: set[tuple[str, str]] = set()
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split("|||")
            if len(parts) >= 2:
                sender = parts[0].strip()
                subject = parts[1].strip()
                key = (sender, subject)
                if key in seen:
                    logger.debug(f"📧 Doublon ignoré : {subject[:40]}")
                    continue
                seen.add(key)
                mails.append({
                    "sender": sender,
                    "subject": subject,
                    "date": parts[2].strip() if len(parts) > 2 else "",
                    "body": "",
                })
        return mails

    # ── Traitement UN PAR UN ─────────────────────────────────────────────

    async def _process_single_mail(self, mail: Dict[str, str]) -> Dict[str, Any]:
        """Traite UN seul mail : analyse → classification → action."""
        sender = mail.get("sender", "inconnu")
        subject = mail.get("subject", "(sans sujet)")
        body = mail.get("body", "")

        # 1. Classifier avec LLM (sémaphore 3 slots max pour ne pas saturer Ollama)
        prompt = _CLASSIFICATION_PROMPT.format(
            sender=sender, subject=subject, body=body[:500]
        )
        async with self._ollama_sem:
            response = await self.ask_llm_async(
                prompt,
                system_prompt="Tu es un classificateur de mails. JSON uniquement.",
                model="speed",
                temperature=0.2,
                max_tokens=200,
            )

        # 2. Parser le JSON
        classification = self._parse_classification(response)

        # 3. Agir selon la classification
        action_taken = await self._act_on_classification(mail, classification)

        return {
            "sender": sender,
            "subject": subject,
            "classification": classification,
            "action_taken": action_taken,
        }

    def _parse_classification(self, response: str) -> Dict[str, Any]:
        """Parse la réponse LLM en dict de classification."""
        try:
            match = re.search(r'\{[^}]+\}', response, re.DOTALL)
            if match:
                result: Dict[str, Any] = json.loads(match.group())
                return result
        except (json.JSONDecodeError, AttributeError):
            pass
        # Fallback si parsing échoue
        return {"type": "pro", "priorite": 3, "action": "lire",
                "resume": "classification échouée", "contient_reunion": False,
                "contient_deadline": False}

    async def _act_on_classification(
        self, mail: Dict[str, str], classification: Dict[str, Any]
    ) -> str:
        """Agit selon la classification du mail."""
        mail_type = classification.get("type", "pro")
        subject = mail.get("subject", "")
        sender = mail.get("sender", "")
        actions = []

        # Spam → ignorer silencieusement
        if mail_type == "spam":
            logger.info(f"📧 Spam ignoré : {subject[:50]}")
            return "ignoré (spam)"

        # Pub → noter en 1 ligne
        if mail_type == "pub":
            logger.info(f"📢 Pub : {subject[:50]}")
            return "pub notée"

        # Urgent → notification vocale immédiate (non bloquante)
        if mail_type == "urgent" or classification.get("priorite", 0) >= 4:
            asyncio.create_task(self._notify_urgent(sender, subject))
            actions.append("notification urgente")

        # Réunion détectée → CalendarAgent
        if classification.get("contient_reunion"):
            result = await self._notify_calendar(subject, sender)
            actions.append(result)

        # Deadline détectée → ReminderAgent
        if classification.get("contient_deadline"):
            result = await self._notify_reminder(subject, sender)
            actions.append(result)

        # Suggestion de réponse pour mails pro/urgent
        if mail_type in ("pro", "urgent", "personnel") and classification.get("priorite", 0) >= 3:
            suggestion = await self._suggest_reply(sender, subject, mail.get("body", ""))
            if suggestion:
                # Stocker la suggestion dans la classification pour le résumé
                classification["suggestion_reponse"] = suggestion

        if actions:
            return " + ".join(actions)
        return "analysé"

    # ── FIX 1A — Notification CalendarAgent ──────────────────────────────

    async def _notify_calendar(self, subject: str, sender: str) -> str:
        """Signale une réunion détectée au CalendarAgent."""
        logger.info(f"📅 Réunion détectée dans mail de {sender}: {subject[:50]}")
        try:
            # Accès au registre via l'attribut injecté par le cortex
            registry = getattr(self, "_registry", None)
            if registry:
                agent = registry.get_agent("CalendarAgent")
                if agent:
                    # Extraire date/heure via executor (évite de bloquer l'event loop)
                    _loop = asyncio.get_running_loop()
                    hint = await _loop.run_in_executor(
                        None,
                        lambda: self.ask_llm(
                            f"Extrais la date et l'heure de cette réunion (JSON: {{\"date\":\"YYYY-MM-DD\",\"heure\":\"HH:MM\"}}). "
                            f"Sujet: {subject}. Si pas de date, mets demain 10h.",
                            model="qwen2.5:0.5b", temperature=0.1, max_tokens=80,
                        ),
                    )
                    data = self.extract_json_from_response(hint)
                    date_str = data.get("date", "") if data else ""
                    heure = data.get("heure", "10:00") if data else "10:00"
                    if date_str:
                        full_date = f"{date_str} {heure}"
                        await agent.execute_tool("add_event", {"title": f"Réunion: {subject[:40]}", "date": full_date})
                        return f"réunion → calendrier ({full_date})"
        except Exception as e:
            logger.debug(f"CalendarAgent non disponible: {e}")
        return "réunion détectée"

    # ── FIX 2A — Notification ReminderAgent ──────────────────────────────

    async def _notify_reminder(self, subject: str, sender: str) -> str:
        """Signale une deadline détectée au ReminderAgent."""
        logger.info(f"⏰ Deadline détectée dans mail de {sender}: {subject[:50]}")
        try:
            registry = getattr(self, "_registry", None)
            if registry:
                agent = registry.get_agent("ReminderAgent")
                if agent:
                    # Extraire la date limite via executor (évite de bloquer l'event loop)
                    _loop = asyncio.get_running_loop()
                    hint = await _loop.run_in_executor(
                        None,
                        lambda: self.ask_llm(
                            f"Extrais la date limite (JSON: {{\"date\":\"YYYY-MM-DD\",\"heure\":\"HH:MM\"}}). "
                            f"Sujet: {subject}. Si pas de date, mets dans 3 jours.",
                            model="qwen2.5:0.5b", temperature=0.1, max_tokens=80,
                        ),
                    )
                    data = self.extract_json_from_response(hint)
                    date_str = data.get("date") if data else None
                    time_str = data.get("heure") if data else None
                    await agent.execute_tool("create_reminder", {
                        "title": f"Deadline: {subject[:40]}",
                        "date": date_str,
                        "time": time_str,
                    })
                    return f"deadline → rappel ({date_str or 'sans date'})"
        except Exception as e:
            logger.debug(f"ReminderAgent non disponible: {e}")
        return "deadline détectée"

    # ── FIX 3A — Notification vocale urgente (non bloquante) ─────────────

    async def _notify_urgent(self, sender: str, subject: str) -> None:
        """Notification macOS + voix Aurélie pour mail urgent."""
        # Notification macOS native
        sender_safe = sender.replace('"', "'")[:30]
        subject_safe = subject.replace('"', "'")[:40]
        notif = (
            f'display notification "De {sender_safe}: {subject_safe}" '
            f'with title "Mail urgent" subtitle "Lucie"'
        )
        await self._run_applescript(notif, timeout=5.0)

        # Voix Aurélie — fire-and-forget via main thread
        try:
            from PyObjCTools import AppHelper
            from app.ui.voice_manager import VoiceManager
            vm = VoiceManager()
            AppHelper.callAfter(vm.speak, f"Lucie : mail urgent de {sender_safe}")
        except Exception as _e:
            logger.debug(f"Voix Aurélie non disponible : {_e}")

        logger.info(f"🚨 Mail urgent : {sender} — {subject[:50]}")

    # ── FIX 4A — Suggestion de réponse LLM ──────────────────────────────

    async def _suggest_reply(self, sender: str, subject: str, body: str) -> Optional[str]:
        """Génère une suggestion de réponse courte (2-3 phrases). Timeout-safe."""
        try:
            prompt = (
                f"Suggère une réponse courte et professionnelle à ce mail. "
                f"2-3 phrases max. Français.\n\n"
                f"De: {sender}\nSujet: {subject}\n"
                f"Contenu: {body[:200] if body else '(pas de contenu)'}"
            )
            loop = asyncio.get_running_loop()
            suggestion = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.ask_llm(prompt, model="balanced", temperature=0.5, max_tokens=150),
                ),
                timeout=5.0,
            )
            if suggestion and not suggestion.startswith("Erreur"):
                return suggestion.strip()
        except (asyncio.TimeoutError, Exception) as e:
            logger.debug(f"Suggestion réponse échouée (non bloquant): {e}")
        return None

    # ── Outil principal : process_inbox ───────────────────────────────────

    async def _tool_process_inbox(self, limit: int = 10) -> str:
        """Traite les mails non lus un par un."""
        start = time.time()

        # Compter les non lus
        ok, count_str = await self._run_applescript(
            'tell application "Mail"\nreturn unread count of inbox\nend tell',
            timeout=5.0,
        )
        unread = int(count_str) if ok else 0

        if unread == 0:
            return "📮 Aucun mail non lu."

        # Récupérer les mails
        try:
            mails = await self._fetch_unread_mails(min(limit, unread))
        except ToolExecutionError as e:
            return str(e)

        if not mails:
            return "📮 Aucun mail non lu récupérable."

        # Traiter les mails en parallèle (sémaphore Ollama = 3 slots)
        if not hasattr(self, "_last_suggestions"):
            self._last_suggestions: Dict[Tuple[str, str], str] = {}
        logger.info(f"📧 Traitement parallèle de {len(mails)} mails")
        raw_results = await asyncio.gather(
            *[self._process_single_mail(mail) for mail in mails],
            return_exceptions=True,
        )
        results: List[Dict[str, Any]] = []
        for i, (mail, result) in enumerate(zip(mails, raw_results)):
            if isinstance(result, BaseException):
                logger.warning(f"📧 Mail {i+1} échoué : {result}")
                continue
            assert isinstance(result, dict)
            results.append(result)
            # Mettre en cache les suggestions pour _tool_reply_mail
            suggestion = result.get("classification", {}).get("suggestion_reponse")
            if suggestion:
                key = (
                    mail.get("subject", "").lower()[:30],
                    mail.get("sender", "").lower()[:30],
                )
                self._last_suggestions[key] = suggestion
            # Mémoriser le dernier sujet urgent
            if "urgent" in result.get("action_taken", ""):
                self._last_urgent_subject = mail.get("subject", "")

        duration = time.time() - start
        return self._build_summary(results, unread, duration)

    # ── Outil : analyser un mail seul ────────────────────────────────────

    async def _tool_analyze_single_mail(self, sender: str, subject: str, body: str = "") -> str:
        """Analyse un seul mail passé en paramètre."""
        mail = {"sender": sender, "subject": subject, "body": body}
        result = await self._process_single_mail(mail)
        cl = result["classification"]

        type_emoji = {"spam": "🚫", "pub": "📢", "pro": "💼", "urgent": "🔴", "personnel": "👤"}
        emoji = type_emoji.get(cl.get("type", ""), "📧")
        prio = cl.get("priorite", 3)

        output = (
            f"{emoji} **{cl.get('type', '?').upper()}** — Priorité {'🔴' * prio}{'⚪' * (5 - prio)}\n"
            f"📝 {cl.get('resume', subject)}\n"
            f"⚡ Action : {result['action_taken']}\n"
        )
        if cl.get("contient_reunion"):
            output += "📅 Réunion détectée\n"
        if cl.get("contient_deadline"):
            output += "⏰ Deadline détectée\n"
        return output

    # ── Outil : répondre à un mail ───────────────────────────────────────

    async def _tool_reply_mail(
        self,
        subject: str = "",
        sender: str = "",
        content: str = "",
    ) -> str:
        """Prépare une réponse — aperçu avant ouverture dans Mail.app."""
        # Récupérer suggestion si content vide
        if not content:
            content = self._get_cached_suggestion(subject, sender)
        if not content:
            return "Aucune suggestion disponible. Précise le contenu de la réponse."

        # Stocker pour confirmation
        self._pending_reply = {
            "subject": subject,
            "sender": sender,
            "content": content,
        }
        self._pending_compose = None

        return (
            f"📧 **Réponse prête pour** : {subject[:50] or '(dernier mail)'}\n\n"
            f"📝 Contenu :\n{content}\n\n"
            f"Tape **'confirme'** pour ouvrir dans Mail.app ou **'annule'** pour abandonner."
        )

    async def _tool_compose_mail(
        self,
        to: str = "",
        subject: str = "",
        content: str = "",
    ) -> str:
        """Compose un nouveau mail — aperçu avant ouverture dans Mail.app."""
        # Génération LLM si content vide
        if not content and subject:
            try:
                loop = asyncio.get_running_loop()
                content = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self.ask_llm(
                            f"Rédige un mail court et professionnel en français.\n"
                            f"Destinataire: {to or '(non précisé)'}\n"
                            f"Sujet: {subject}\n"
                            f"2-4 phrases max. Pas de signature.",
                            model="balanced", temperature=0.5, max_tokens=150,
                        ),
                    ),
                    timeout=8.0,
                )
            except Exception:
                content = ""

        if not content:
            return "Précise au moins le sujet du mail pour que je puisse rédiger."

        # Stocker pour confirmation
        self._pending_compose = {
            "to": to,
            "subject": subject,
            "content": content,
        }
        self._pending_reply = None

        return (
            f"📧 **Nouveau mail prêt**\n"
            f"À : {to or '(à préciser dans Mail.app)'}\n"
            f"Sujet : {subject or '(à préciser)'}\n\n"
            f"📝 Contenu :\n{content}\n\n"
            f"Tape **'confirme'** pour ouvrir dans Mail.app ou **'annule'** pour abandonner."
        )

    def _get_cached_suggestion(self, subject: str, sender: str) -> str:
        """Récupère la suggestion du dernier process_inbox."""
        if not hasattr(self, "_last_suggestions"):
            return ""
        key = (subject.lower()[:30], sender.lower()[:30])
        return self._last_suggestions.get(key, "")

    # ── Outil : confirmer ou annuler ──────────────────────────────────────

    async def _tool_confirm_mail(self, action: str = "confirm") -> str:
        """Confirme ou annule l'action mail en attente."""
        pending_reply = getattr(self, "_pending_reply", None)
        pending_compose = getattr(self, "_pending_compose", None)

        if action == "cancel":
            self._pending_reply = None
            self._pending_compose = None
            if pending_reply or pending_compose:
                return "📧 Action annulée."
            return "Aucune action mail en attente."

        # Confirmer un reply
        if pending_reply:
            self._pending_reply = None
            return await self._execute_reply_applescript(pending_reply)

        # Confirmer un compose
        if pending_compose:
            self._pending_compose = None
            return await self._execute_compose_applescript(pending_compose)

        return "Aucune action mail en attente à confirmer."

    async def _execute_reply_applescript(self, data: Dict[str, Any]) -> str:
        """Ouvre la fenêtre reply dans Mail.app via AppleScript."""
        safe_content = data["content"].replace('"', '\\"').replace('\n', '\\n')
        safe_subject = data["subject"].replace('"', '\\"')
        script = f'''
tell application "Mail"
    set targetMsg to missing value
    repeat with m in (messages of inbox)
        if subject of m contains "{safe_subject}" then
            set targetMsg to m
            exit repeat
        end if
    end repeat
    if targetMsg is missing value then
        return "NOTFOUND"
    end if
    set theReply to reply targetMsg with opening window
    set content of theReply to "{safe_content}"
    return "OK"
end tell
'''
        success, output = await self._run_applescript(script, timeout=10.0)
        if success and "OK" in output:
            logger.info(f"📧 Réponse ouverte dans Mail.app : {data['subject'][:40]}")
            return "✅ Fenêtre de réponse ouverte. Tu peux relire et envoyer."
        if "NOTFOUND" in output:
            return f"❌ Mail introuvable : {data['subject'][:40]}"
        return f"❌ Erreur Mail.app : {output}"

    async def _execute_compose_applescript(self, data: Dict[str, Any]) -> str:
        """Ouvre une nouvelle fenêtre de composition dans Mail.app."""
        safe_to = data.get("to", "").replace('"', '\\"')
        safe_subject = data.get("subject", "").replace('"', '\\"')
        safe_content = data.get("content", "").replace('"', '\\"').replace('\n', '\\n')
        script = f'''
tell application "Mail"
    activate
    set newMsg to make new outgoing message with properties {{visible:true, subject:"{safe_subject}", content:"{safe_content}"}}
    if "{safe_to}" is not "" then
        tell newMsg
            make new to recipient at end of to recipients with properties {{address:"{safe_to}"}}
        end tell
    end if
    return "OK"
end tell
'''
        success, output = await self._run_applescript(script, timeout=10.0)
        if success and "OK" in output:
            logger.info(f"📧 Nouveau mail ouvert dans Mail.app : {data.get('subject', '')[:40]}")
            return "✅ Nouveau mail ouvert dans Mail.app. Tu peux relire et envoyer."
        return f"❌ Erreur Mail.app : {output}"

    # ── Outil : surveiller inbox ─────────────────────────────────────────

    async def _tool_watch_inbox(self, interval: int = 300) -> str:
        """Lance la surveillance continue de l'inbox."""
        if self._watch_task and not self._watch_task.done():
            return "📧 Surveillance déjà active."

        ok, count_str = await self._run_applescript(
            'tell application "Mail"\nreturn unread count of inbox\nend tell',
            timeout=5.0,
        )
        self._last_unread = int(count_str) if ok else 0

        try:
            loop = asyncio.get_running_loop()
            self._watch_task = loop.create_task(self._watch_loop(interval))
        except RuntimeError:
            return "⚠️ Pas de boucle asyncio — surveillance impossible"

        logger.info(f"📧 Surveillance inbox démarrée (toutes les {interval}s)")
        return f"✅ Surveillance inbox active (vérification toutes les {interval // 60}min)"

    async def _watch_loop(self, interval: int) -> None:
        """Boucle de surveillance inbox."""
        while True:
            try:
                await asyncio.sleep(interval)
                ok, count_str = await self._run_applescript(
                    'tell application "Mail"\nreturn unread count of inbox\nend tell',
                    timeout=5.0,
                )
                if not ok:
                    continue
                current = int(count_str)
                if current > self._last_unread:
                    new_count = current - self._last_unread
                    self._last_unread = current
                    logger.info(f"📧 {new_count} nouveau(x) mail(s)")
                    await self._run_applescript(
                        f'display notification "{new_count} nouveau(x) mail(s)" '
                        f'with title "📧 Lucie" subtitle "Inbox"',
                        timeout=5.0,
                    )
                else:
                    self._last_unread = current
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erreur surveillance inbox: {e}")
                await asyncio.sleep(60)

    # ── Résumé ───────────────────────────────────────────────────────────

    def _build_summary(self, results: List[Dict[str, Any]], unread: int, duration: float) -> str:
        """Construit le résumé lisible de tous les mails traités."""
        if not results:
            return "📮 Aucun mail traité."

        urgent = [r for r in results if "urgent" in r.get("action_taken", "")]
        spam = [r for r in results if "spam" in r.get("action_taken", "")]
        pub = [r for r in results if "pub" in r.get("action_taken", "")]
        reunions = [r for r in results if "réunion" in r.get("action_taken", "")]
        deadlines = [r for r in results if "deadline" in r.get("action_taken", "")]
        autres = [r for r in results if r not in urgent + spam + pub + reunions + deadlines]

        summary = f"📧 **{len(results)} mails traités** ({unread} non lus au total) — {duration:.1f}s\n\n"

        if urgent:
            summary += f"🔴 **{len(urgent)} URGENT(S)**\n"
            for r in urgent:
                summary += f"  → {r['sender']}: {r['subject']}\n"
                suggestion = r.get("classification", {}).get("suggestion_reponse")
                if suggestion:
                    summary += f"    💡 {suggestion[:100]}\n"
            summary += "\n"

        if reunions:
            summary += f"📅 **{len(reunions)} réunion(s) détectée(s)**\n"
            for r in reunions:
                summary += f"  → {r['subject']}\n"
            summary += "\n"

        if deadlines:
            summary += f"⏰ **{len(deadlines)} deadline(s)**\n"
            for r in deadlines:
                summary += f"  → {r['subject']}\n"
            summary += "\n"

        if autres:
            summary += f"💼 **{len(autres)} professionnel(s)/personnel(s)**\n"
            for r in autres:
                cl = r.get("classification", {})
                summary += f"  → {r['sender']}: {cl.get('resume', r['subject'])}\n"
                suggestion = cl.get("suggestion_reponse")
                if suggestion:
                    summary += f"    💡 Réponse suggérée : {suggestion[:100]}\n"
            summary += "\n"

        if spam:
            summary += f"🚫 {len(spam)} spam(s) ignoré(s)\n"
        if pub:
            summary += f"📢 {len(pub)} pub(s) notée(s)\n"

        return summary.strip()

    async def stop(self) -> None:
        """Arrête la surveillance inbox."""
        if self._watch_task and not self._watch_task.done():
            self._watch_task.cancel()
            self._watch_task = None
        logger.info("📧 SmartMailAgent arrêté")
