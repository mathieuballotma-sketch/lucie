"""
BLOC 1 — Diagnostic réel de Lucie.

Exécute 10 requêtes via engine.process_async() et note :
  - Agent appelé
  - Action physique réelle OUI/NON
  - Erreur si échec
  - Temps de réponse

Usage :
    PYTHONPATH=. python3 tests/test_diagnostic.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import Config
from app.core.engine import LucidEngine
from app.utils.logger import logger

# Requêtes à tester
QUERIES = [
    ("crée un rappel pour demain à 9h", "ReminderAgent ou AppleEcosystemAgent"),
    ("range mes téléchargements", "FileAgent"),
    ("ouvre Notes et crée une note", "ComputerControlAgent + AppleEcosystemAgent"),
    ("ajoute un événement demain à 14h", "CalendarAgent"),
    ("lis mes mails non lus", "AppleEcosystemAgent"),
    ("explique ce code : def hello(): print('hi')", "CodeDebugAgent"),
    ("cherche le cours de l'or", "SafariResearchWorkflow"),
    ("crée un document sur l'intelligence artificielle", "DocumentAgent"),
    ("ouvre Safari", "ComputerControlAgent"),
    ("rappelle-moi d'appeler Paul à 18h", "AppleEcosystemAgent"),
]


async def run_diagnostic():
    """Lance le diagnostic complet."""
    print("=" * 70)
    print("     DIAGNOSTIC LUCIE — BLOC 1")
    print("=" * 70)

    # Initialiser le moteur
    print("\nInitialisation du moteur...")
    config = Config.load()
    engine = LucidEngine(config)

    loop = asyncio.get_running_loop()
    engine.set_loop(loop)
    # Laisser les handlers s'enregistrer
    await asyncio.sleep(2.0)

    print("Moteur prêt.\n")
    print(f"{'#':<3} {'Requête':<50} {'Durée':>8} {'Statut':>8}")
    print(f"{'─'*3} {'─'*50} {'─'*8} {'─'*8}")

    results = []

    for i, (query, expected_agent) in enumerate(QUERIES, 1):
        start = time.time()
        try:
            response, latency = await asyncio.wait_for(
                engine.process_async(query),
                timeout=120.0,
            )
            duration = time.time() - start
            is_error = (
                response.startswith("Erreur")
                or response.startswith("Désolé")
                or "❌" in response[:5]
            )
            has_action = "✅" in response or "ouvert" in response.lower()
            status = "ERREUR" if is_error else "OK"
            results.append({
                "query": query,
                "expected": expected_agent,
                "duration": duration,
                "status": status,
                "action": "OUI" if has_action else "NON",
                "response": response[:120],
                "error": "",
            })
        except asyncio.TimeoutError:
            duration = time.time() - start
            results.append({
                "query": query,
                "expected": expected_agent,
                "duration": duration,
                "status": "TIMEOUT",
                "action": "NON",
                "response": "",
                "error": "Timeout 120s",
            })
        except Exception as e:
            duration = time.time() - start
            results.append({
                "query": query,
                "expected": expected_agent,
                "duration": duration,
                "status": "CRASH",
                "action": "NON",
                "response": "",
                "error": str(e)[:120],
            })

        r = results[-1]
        print(f"{i:<3} {query:<50} {r['duration']:>7.2f}s {r['status']:>8}")

    # Rapport détaillé
    print("\n" + "=" * 70)
    print("     RAPPORT DÉTAILLÉ")
    print("=" * 70)

    for i, r in enumerate(results, 1):
        print(f"\n  [{i}] {r['query']}")
        print(f"      Agent attendu : {r['expected']}")
        print(f"      Statut : {r['status']} | Action physique : {r['action']} | Durée : {r['duration']:.2f}s")
        if r['response']:
            print(f"      Réponse : {r['response']}")
        if r['error']:
            print(f"      Erreur : {r['error']}")

    # Résumé
    ok = sum(1 for r in results if r["status"] == "OK")
    total = len(results)
    print(f"\n{'=' * 70}")
    print(f"  RÉSULTAT : {ok}/{total} requêtes réussies")
    print(f"{'=' * 70}\n")

    # Écrire les résultats dans un fichier
    with open("tests/diagnostic_results.txt", "w") as f:
        for i, r in enumerate(results, 1):
            f.write(f"[{i}] {r['query']}\n")
            f.write(f"    Statut: {r['status']} | Action: {r['action']} | Durée: {r['duration']:.2f}s\n")
            if r['response']:
                f.write(f"    Réponse: {r['response']}\n")
            if r['error']:
                f.write(f"    Erreur: {r['error']}\n")
            f.write("\n")

    # Arrêt propre
    print("Arrêt du moteur...")
    await engine.stop_async()
    print("Terminé.")

    return results


if __name__ == "__main__":
    asyncio.run(run_diagnostic())
