from __future__ import annotations
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class WandererAgent:
    """
    Agent 2 du Self-Healing Network.
    Se balade sur le P2P, lit les machine_logs,
    remonte les epingles a l'Analyzer.
    """

    def __init__(self, network_manager: Any) -> None:
        self._net = network_manager
        self._visited: set[str] = set()
        self._running: bool = False
        self._findings: List[Dict[str, Any]] = []
        self._task: Optional[asyncio.Task[None]] = None
        logger.info("WandererAgent init")

    async def start(self) -> None:
        """Demarre le Wanderer en arriere-plan."""
        self._running = True
        self._task = asyncio.create_task(self._wander_loop())
        logger.info("Wanderer demarre")

    def stop(self) -> None:
        self._running = False

    async def _wander_loop(self) -> None:
        while self._running:
            peers = self._net.healthy_peers
            if peers:
                for peer in peers:
                    await self._visit(peer)
                    await asyncio.sleep(5)
            else:
                logger.debug("Wanderer : aucun pair disponible")
            await asyncio.sleep(30)

    async def _visit(self, peer: Any) -> None:
        """Visite un noeud et analyse ses logs."""
        logger.info(f"Wanderer visite : {peer.address}")
        self._visited.add(peer.node_id)

        # Recupere les logs du pair
        response = await self._net.send(peer, {
            "type": "get_logs",
            "limit": 100,
        })
        if not response or response.get("type") != "logs":
            return

        logs = response.get("data", [])
        if not logs:
            return

        # Analyse les logs
        findings = self._analyze_remote_logs(logs, peer.node_id)
        if findings:
            self._findings.extend(findings)
            logger.info(
                f"Wanderer : {len(findings)} anomalie(s) "
                f"sur {peer.address}"
            )
            # Partage les correctifs locaux si on en a
            await self._share_local_fixes(peer)

    def _analyze_remote_logs(self, logs: List[Dict[str, Any]], node_id: str) -> List[Dict[str, Any]]:
        """Analyse les logs d'un noeud distant."""
        from collections import Counter
        findings = []

        errors = [entry for entry in logs if entry.get("result") in ("error", "timeout")]
        if not errors:
            return []

        tool_errors = Counter(e.get("tool","unknown") for e in errors)
        for tool, count in tool_errors.most_common(3):
            if count >= 2:
                findings.append({
                    "node_id": node_id,
                    "tool": tool,
                    "error_count": count,
                    "timestamp": time.time(),
                    "source": "wanderer",
                })

        return findings

    async def _share_local_fixes(self, peer: Any) -> None:
        """Partage les correctifs locaux avec un pair."""
        fixes_path = Path("memory/journals/fixes.jsonl")
        if not fixes_path.exists():
            return
        fixes = []
        with open(fixes_path,"r",encoding="utf-8") as f:
            for line in f:
                try:
                    fix = json.loads(line)
                    if not fix.get("shared"):
                        fixes.append(fix)
                except Exception:
                    continue
        if fixes:
            await self._net.send(peer, {
                "type": "share_fix",
                "fix": fixes[-1],  # Partage le plus recent
            })
            logger.info(f"Fix partage avec {peer.address}")

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "visited": len(self._visited),
            "findings": len(self._findings),
            "running": self._running,
        }
