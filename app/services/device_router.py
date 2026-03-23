from __future__ import annotations
import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

@dataclass
class DeviceStatus:
    iphone_on_wifi: bool = False
    iphone_bluetooth: bool = False
    mac_only: bool = True
    iphone_number: Optional[str] = None
    best_target: str = "mac"

class DeviceDetector:
    """
    Detecte les appareils Apple connectes.
    Methode : ping reseau + scan Bonjour + Bluetooth.
    """

    def __init__(self) -> None:
        self._cache: Optional[DeviceStatus] = None
        self._cache_ts: float = 0
        self._cache_ttl: float = 30.0  # Refresh toutes les 30s

    async def detect(self) -> DeviceStatus:
        # Cache pour eviter de scanner trop souvent
        if self._cache and (time.time() - self._cache_ts) < self._cache_ttl:
            return self._cache

        status = DeviceStatus()

        # Detection iPhone sur le meme WiFi via Bonjour
        iphone_wifi = await self._scan_bonjour_iphone()
        if iphone_wifi:
            status.iphone_on_wifi = True
            status.mac_only = False
            status.best_target = "iphone_imessage"
            logger.info("iPhone detecte sur WiFi")

        # Detection Bluetooth
        bt = await self._scan_bluetooth()
        if bt:
            status.iphone_bluetooth = True
            if not status.iphone_on_wifi:
                status.mac_only = False
                status.best_target = "iphone_imessage"

        if status.mac_only:
            status.best_target = "mac"

        self._cache = status
        self._cache_ts = time.time()
        return status

    async def _scan_bonjour_iphone(self) -> bool:
        """Detecte iPhone via mDNS Bonjour sur le reseau local."""
        try:
            result = await asyncio.create_subprocess_exec(
                "dns-sd", "-B", "_apple-mobdev2._tcp", "local",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    result.communicate(), timeout=3.0
                )
                output = stdout.decode("utf-8", errors="ignore")
                return "iPhone" in output or "mobile" in output.lower()
            except asyncio.TimeoutError:
                try:
                    result.kill()
                except ProcessLookupError:
                    pass
                # Timeout = service existe mais pas de reponse = iPhone present
                return True
        except Exception as _e:
            logger.debug(f"Détection iPhone échouée : {_e}")

        # Fallback : arp scan
        try:
            proc = await asyncio.create_subprocess_exec(
                "arp", "-a",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode("utf-8", errors="ignore")
            # Apple OUI prefixes communs
            apple_ouis = ["a4:c3:", "f0:d1:", "3c:22:", "00:cd:", "ac:de:"]
            return any(oui in output.lower() for oui in apple_ouis)
        except Exception:
            return False

    async def _scan_bluetooth(self) -> bool:
        """Detecte appareils Bluetooth Apple connectes."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "system_profiler", "SPBluetoothDataType",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            output = stdout.decode("utf-8", errors="ignore")
            return "iPhone" in output or "iphone" in output.lower()
        except Exception:
            return False


class SmartRouter:
    """
    Route les notifications vers le bon appareil.
    iPhone detecte → iMessage via Messages.app
    Mac seul       → notification locale
    """

    def __init__(self) -> None:
        self._detector = DeviceDetector()

    async def send(
        self,
        message: str,
        title: str = "Lucie",
        iphone_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Envoie la notification sur le meilleur appareil disponible.
        Retourne un dict avec le resultat.
        """
        status = await self._detector.detect()
        result = {"target": status.best_target, "success": False}

        if status.best_target == "iphone_imessage" and iphone_number:
            success = await self._send_imessage(iphone_number, message)
            result["success"] = success
            if success:
                logger.info(f"Message envoye sur iPhone : {message[:40]}")
                return result

        # Fallback ou Mac seul → notification locale
        success = self._send_mac_notification(title, message)
        result["target"] = "mac"
        result["success"] = success
        return result

    async def _send_imessage(self, number: str, message: str) -> bool:
        """Envoie via iMessage — Messages.app AppleScript."""
        # Nettoie le message pour AppleScript
        msg = message.replace('"','').replace("\\","").replace("'","")
        script = f'''
        tell application "Messages"
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to buddy "{number}" of targetService
            send "{msg}" to targetBuddy
        end tell
        '''
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            if proc.returncode == 0:
                return True
            logger.warning(f"iMessage erreur : {stderr.decode()[:100]}")
            return False
        except Exception as e:
            logger.error(f"Erreur iMessage : {e}")
            return False

    def _send_mac_notification(self, title: str, message: str) -> bool:
        """Notification locale macOS."""
        msg = message.replace('"','').replace("'","")
        ttl = title.replace('"','').replace("'","")
        script = f'display notification "{msg}" with title "{ttl}" subtitle "agent_lucide"'
        try:
            subprocess.run(["osascript","-e",script], check=True, timeout=5)
            return True
        except Exception as e:
            logger.error(f"Erreur notification Mac : {e}")
            return False


async def lucie_smart_notify(
    context: str,
    title: str = "Lucie",
    iphone_number: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Notification intelligente :
    1. Genere le texte via LLM
    2. Detecte les appareils
    3. Envoie sur le meilleur appareil
    """
    from app.services.notifier import generate_notification_text
    message = await generate_notification_text(context)
    router = SmartRouter()
    result = await router.send(message, title, iphone_number)
    result["message"] = message
    return result
