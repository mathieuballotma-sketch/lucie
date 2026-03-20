"""Test de vitesse — validation des temps de réponse < 2s."""
import asyncio
import time
import sys

sys.path.insert(0, ".")

from app.core.config import Config
from app.core.engine import LucidEngine


import pytest

@pytest.mark.asyncio
async def test():
    config = Config.load()
    engine = LucidEngine(config)
    loop = asyncio.get_running_loop()
    engine.set_loop(loop)
    await asyncio.sleep(6)  # warmup nano + speed

    print("=== SPEED TEST ===", flush=True)
    tests = [
        "bonjour",
        "salut",
        "merci",
        "ouvre Safari",
        "comment tu vas",
        "cest quoi python",
    ]

    all_ok = True
    for q in tests:
        t0 = time.perf_counter()
        r, _ = await engine.process_async(q)
        ms = (time.perf_counter() - t0) * 1000
        tag = "OK" if ms < 2000 else "LENT"
        if ms >= 2000:
            all_ok = False
        print(f"  {tag} {ms:>6.0f}ms | {q:<25} -> {r[:50]}", flush=True)

    print("=== DONE ===", flush=True)
    await engine.stop_async()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    asyncio.run(test())
