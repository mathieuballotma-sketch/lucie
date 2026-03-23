"""
AnalyzerAgent — détecte les patterns d erreurs et pose des épingles
"""
from __future__ import annotations
import json
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List

logger = logging.getLogger(__name__)
ERROR_LOG = Path("memory/journals/error_log.jsonl")
PINS_LOG  = Path("memory/journals/pins.jsonl")

@dataclass
class Pin:
    pattern: str
    tool: str
    severity: str
    occurrences: int
    example_error: str
    fix_hint: str
    fixed: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_token(self) -> str:
        return (
            f"[FLAG:{self.severity.upper()}]"
            f"[PATTERN:{self.pattern}]"
            f"[TOOL:{self.tool}]"
            f"[COUNT:{self.occurrences}]"
            f"[HINT:{self.fix_hint[:60]}]"
            f"[FIXED:{self.fixed}]"
        )

class AnalyzerAgent:
    _SEVERITY_THRESHOLDS = {"critical":10,"high":5,"medium":3,"low":1}

    def __init__(self) -> None:
        PINS_LOG.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Analyzer init")

    def analyze(self) -> List[Pin]:
        errors = self._load_errors()
        if not errors:
            return []
        pins = []
        tool_errors = Counter(e.get("tool","unknown") for e in errors)
        for tool, count in tool_errors.most_common():
            sev = self._get_severity(count)
            ex = next((e.get("error_msg","") for e in errors if e.get("tool")==tool),"unknown")
            pins.append(Pin(
                pattern=f"recurring_error:{tool}", tool=tool, severity=sev,
                occurrences=count, example_error=ex or "no message",
                fix_hint=f"Verifier {tool} — {count} erreurs",
            ))
        timeouts = [e for e in errors if e.get("result")=="timeout"]
        if timeouts:
            for tool, count in Counter(str(e.get("tool", "")) for e in timeouts).most_common():
                pins.append(Pin(
                    pattern="timeout_loop", tool=tool,
                    severity=self._get_severity(count*2), occurrences=count,
                    example_error="timeout", fix_hint=f"Augmenter timeout {tool}",
                ))
        cons = self._find_consecutive_errors(errors)
        if cons > 3:
            pins.append(Pin(
                pattern="cascade_failure", tool="system", severity="critical",
                occurrences=cons, example_error="cascade",
                fix_hint="Verifier connexion Ollama",
            ))
        self._save_pins(pins)
        return pins

    def get_unfixed_pins(self) -> List[Pin]:
        if not PINS_LOG.exists():
            return []
        pins = []
        with open(PINS_LOG,"r",encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if not data.get("fixed",False):
                        pins.append(Pin(**{k:v for k,v in data.items() if k in Pin.__dataclass_fields__}))
                except Exception as e:
                    logger.warning(f"Pin invalide ignoré: {e}")
                    continue
        return pins

    def _load_errors(self) -> list[dict[str, Any]]:
        if not ERROR_LOG.exists():
            return []
        errors = []
        with open(ERROR_LOG,"r",encoding="utf-8") as f:
            for line in f:
                try:
                    errors.append(json.loads(line))
                except Exception as e:
                    logger.warning(f"Entrée erreur invalide ignorée: {e}")
                    continue
        return errors

    def _get_severity(self, count: int) -> str:
        for sev, th in self._SEVERITY_THRESHOLDS.items():
            if count >= th:
                return sev
        return "low"

    def _find_consecutive_errors(self, errors: list[dict[str, Any]]) -> int:
        max_seq = current = 0
        for e in errors:
            if e.get("result") in ("error","timeout"):
                current += 1
                max_seq = max(max_seq, current)
            else:
                current = 0
        return max_seq

    def _save_pins(self, pins: List[Pin]) -> None:
        with open(PINS_LOG,"a",encoding="utf-8") as f:
            for pin in pins:
                data = {
                    "pattern":pin.pattern,"tool":pin.tool,"severity":pin.severity,
                    "occurrences":pin.occurrences,"example_error":pin.example_error,
                    "fix_hint":pin.fix_hint,"fixed":pin.fixed,"timestamp":pin.timestamp,
                    "token":pin.to_token(),
                }
                f.write(json.dumps(data,ensure_ascii=False)+"\n")
