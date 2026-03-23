"""BLOC 10 — Test de validation finale 8->10.

Script standalone — lancer avec :
    PYTHONPATH=. python3 tests/test_final.py

Ne pas lancer avec pytest (nécessite Ollama actif).
"""
import asyncio, time, sys, signal
sys.path.insert(0, ".")


async def _run_final_validation():
    """Exécute la validation finale complète avec Ollama."""
    signal.alarm(180)

    from app.core.config import Config
    from app.core.engine import LucidEngine

    config = Config.load()
    engine = LucidEngine(config)
    loop = asyncio.get_running_loop()
    engine.set_loop(loop)
    await asyncio.sleep(2.0)

    tests = [
        ("bonjour", "salutation"),
        ("crée un rappel pour demain à 9h", "ReminderAgent"),
        ("ouvre Safari", "ComputerControlAgent"),
        ("ouvre Notes et crée une note", "multi"),
        ("rappelle-moi d'appeler Paul à 18h", "AppleEcosystemAgent"),
        ("lis mes mails non lus", "AppleEcosystemAgent"),
        ("explique ce code : def hello(): print('hi')", "CodeDebugAgent"),
        ("surveille le bitcoin et préviens-moi si ça passe 100000", "WatchAgent"),
    ]

    score = 0
    for query, expected in tests:
        start = time.time()
        try:
            response, lat = await asyncio.wait_for(
                engine.process_async(query), timeout=60
            )
            dur = time.time() - start
            ok = response and len(response) > 5 and not response.startswith("Désolé")
            if ok:
                score += 1
            status = "OK" if ok else "FAIL"
            print(f"RESULT {status} | {dur:5.1f}s | {query[:45]:<45} -> {response[:70]}")
        except Exception as e:
            dur = time.time() - start
            print(f"RESULT FAIL | {dur:5.1f}s | {query[:45]:<45} -> {e}")

    print(f"\nSCORE {score}/{len(tests)}")
    await engine.stop_async()


if __name__ == "__main__":
    asyncio.run(_run_final_validation())
