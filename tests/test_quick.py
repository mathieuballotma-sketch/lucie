"""Test rapide de validation des corrections."""
import asyncio, time, sys, signal
sys.path.insert(0, ".")

# Auto-kill après 120s
signal.alarm(120)

async def quick_test():
    from app.core.config import Config
    from app.core.engine import LucidEngine

    config = Config.load()
    engine = LucidEngine(config)
    loop = asyncio.get_running_loop()
    engine.set_loop(loop)
    await asyncio.sleep(2.0)

    tests = [
        "bonjour",
        "ouvre Safari",
        "crée un rappel pour demain à 9h",
        "ouvre Notes et crée une note",
        "rappelle-moi d'appeler Paul à 18h",
    ]

    ok_count = 0
    for q in tests:
        start = time.time()
        try:
            response, lat = await asyncio.wait_for(engine.process_async(q), timeout=30)
            dur = time.time() - start
            fail = response.startswith("Erreur") or response.startswith("Désolé")
            status = "FAIL" if fail else "OK"
            if not fail:
                ok_count += 1
            print(f"RESULT {status} | {dur:.1f}s | {q} -> {response[:90]}")
        except Exception as e:
            print(f"RESULT FAIL | {time.time()-start:.1f}s | {q} -> {e}")

    await engine.stop_async()
    print(f"SCORE {ok_count}/{len(tests)}")

asyncio.run(quick_test())
