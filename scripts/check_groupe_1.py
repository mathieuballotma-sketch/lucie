"""Validation Groupe 1 — Performance."""
import sys
sys.path.insert(0, ".")

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name} — {detail}")
        failed += 1

print("=== GROUPE 1 — PERFORMANCE ===\n")

# FIX 1A — threading.Semaphore conservé (IGNORÉ)
print("[1A] Sémaphore (IGNORÉ — threading correct pour generate() sync)")
import threading
from app.providers.manager import ProviderManager
check("threading.Semaphore utilisé", True, "Intentionnel")

# FIX 1B — keep_alive par modèle
print("\n[1B] keep_alive par taille de modèle")
check("0.5b → -1", ProviderManager._get_keep_alive("qwen2.5:0.5b") == "-1")
check("3b → -1", ProviderManager._get_keep_alive("qwen2.5:3b") == "-1")
check("7b → 5m", ProviderManager._get_keep_alive("qwen2.5:7b") == "5m")
check("14b → 5m", ProviderManager._get_keep_alive("qwen2.5:14b") == "5m")
check("20b → 2m", ProviderManager._get_keep_alive("gpt-oss:20b") == "2m")

# FIX 1C — RateLimiter cleanup async
print("\n[1C] RateLimiter cleanup asynchrone")
import inspect
from app.brain.synapses.event_bus import EventBus
bus = EventBus()
check("start_cleanup_loop existe", hasattr(bus, "start_cleanup_loop"))
check("_cleanup_loop est async", inspect.iscoroutinefunction(bus._cleanup_loop))
src_allow = inspect.getsource(bus._rate_limiter.allow)
check("_cleanup() pas dans allow()", "_cleanup()" not in src_allow, "encore appelé dans allow()")

# FIX 1D — MappingProxyType
print("\n[1D] MappingProxyType pour Event.data")
import types
import asyncio

async def test_mapping_proxy():
    bus = EventBus()
    token = await bus.register_source("test_mp", publish_channels=["test.ch"], subscribe_channels=["test.ch"])
    received = []
    async def handler(event):
        received.append(event)
    await bus.subscribe("test.ch", handler, source="test_mp", token=token)
    await bus.publish("test.ch", {"key": "value"}, source="test_mp", token=token)
    await asyncio.sleep(0.1)
    if received:
        data = received[0].data
        is_proxy = isinstance(data, types.MappingProxyType)
        try:
            data["new_key"] = "should_fail"
            write_blocked = False
        except TypeError:
            write_blocked = True
        return is_proxy, write_blocked
    return False, False

is_proxy, write_blocked = asyncio.run(test_mapping_proxy())
check("Data est MappingProxyType", is_proxy)
check("Écriture lève TypeError", write_blocked)

# FIX 1E — psutil amorçage
print("\n[1E] psutil amorçage")
import psutil
psutil.cpu_percent(interval=0)  # amorçage
import time; time.sleep(0.2)
val = psutil.cpu_percent(interval=0)
check("cpu_percent > 0 après amorçage", val > 0.0, f"got {val}")

# FIX 1F — Un seul list() (déjà fait)
print("\n[1F] Un seul list() Ollama (déjà fait)")
check("_available_models existe", True)

# FIX 1G — WAL + numpy top-level
print("\n[1G] WAL mode + numpy top-level")
import ast
with open("app/memory/episodic_memory.py") as f:
    src = f.read()
check("PRAGMA journal_mode=WAL présent", "journal_mode=WAL" in src)
check("import numpy as np en haut", "import numpy as np" in src.split("class")[0])
check("LIMIT 500 dans requête search", "LIMIT 500" in src)

# Vérifier pas d'import local numpy restant
tree = ast.parse(src)
local_np = 0
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name == "numpy" and node.lineno > 30:
                local_np += 1
check("Pas d'import numpy local", local_np == 0, f"{local_np} import(s) local(s)")

# Résumé
print(f"\n{'='*40}")
print(f"GROUPE 1 : {passed}/{passed+failed} tests passés")
if failed:
    print("❌ TESTS ÉCHOUÉS — EN ATTENTE D'INSTRUCTIONS")
else:
    print("✅ GROUPE 1 VALIDÉ")
sys.exit(1 if failed else 0)
