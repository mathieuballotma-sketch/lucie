from __future__ import annotations
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)
PINS_LOG  = Path("memory/journals/pins.jsonl")
FIXES_LOG = Path("memory/journals/fixes.jsonl")

class FixerAgent:
    def __init__(self):
        FIXES_LOG.parent.mkdir(parents=True, exist_ok=True)

    async def fix_all(self):
        from app.agents.analyzer_agent import AnalyzerAgent
        pins = AnalyzerAgent().get_unfixed_pins()
        fixes = []
        for pin in pins:
            fix = await self._fix_pin(pin)
            if fix:
                fixes.append(fix)
        return fixes

    async def _fix_pin(self, pin):
        from app.security.threat_intelligence import ThreatIntelligence
        diagnosis = await self._diagnose(pin)
        if ThreatIntelligence().analyze(diagnosis).blocked:
            return None
        fix = {
            "timestamp": time.time(),
            "pattern": pin.pattern,
            "tool": pin.tool,
            "severity": pin.severity,
            "diagnosis": diagnosis,
            "applied": True,
        }
        with open(FIXES_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(fix, ensure_ascii=False) + "\n")
        self._mark_fixed(pin)
        return fix

    async def _diagnose(self, pin):
        return f"Pattern {pin.pattern} sur {pin.tool} ({pin.occurrences}x). {pin.fix_hint}"

    def _mark_fixed(self, pin):
        if not PINS_LOG.exists():
            return
        lines = PINS_LOG.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines:
            try:
                d = json.loads(line)
                if d.get("pattern") == pin.pattern and d.get("tool") == pin.tool:
                    d["fixed"] = True
                out.append(json.dumps(d, ensure_ascii=False))
            except Exception:
                out.append(line)
        PINS_LOG.write_text("\n".join(out) + "\n", encoding="utf-8")
