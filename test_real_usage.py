#!/usr/bin/env python3
"""
Script de test QA — simule 5 profils utilisateurs + tests transversaux.
Adapté au fonctionnement réel de LucidEngine (set_loop + process_async).
"""

import asyncio
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import Config
from app.core.engine import LucidEngine


async def test_command(
    engine: LucidEngine,
    command: str,
    profile: str,
    timeout: float = 30.0,
) -> dict[str, str]:
    """Simule une commande utilisateur avec timeout."""
    print(f"\n{'─'*60}")
    print(f"[{profile}] COMMANDE: {command[:80]}")
    sys.stdout.flush()
    start = time.time()

    try:
        response, latency = await asyncio.wait_for(
            engine.process_async(command),
            timeout=timeout,
        )
        elapsed = time.time() - start
        resp_str = str(response)
        print(f"  ✅ OK ({elapsed:.1f}s) — {resp_str[:120]}")
        return {
            "command": command,
            "profile": profile,
            "status": "OK",
            "result": resp_str[:300],
            "latency": f"{elapsed:.1f}s",
        }
    except asyncio.TimeoutError:
        elapsed = time.time() - start
        print(f"  ⏰ TIMEOUT ({elapsed:.0f}s)")
        return {
            "command": command,
            "profile": profile,
            "status": "TIMEOUT",
            "error": f"Timeout après {timeout}s",
        }
    except Exception as e:
        elapsed = time.time() - start
        tb = traceback.format_exc()
        print(f"  ❌ ERREUR ({elapsed:.1f}s): {type(e).__name__}: {e}")
        print(f"     {tb.splitlines()[-2] if len(tb.splitlines()) > 1 else tb}")
        return {
            "command": command,
            "profile": profile,
            "status": "ERROR",
            "error": f"{type(e).__name__}: {e}",
            "traceback": tb,
        }


async def main() -> None:
    print("=" * 60)
    print("TEST QA — Agent Lucide")
    print("=" * 60)

    # ── Initialisation ────────────────────────────────────────────────
    print("\n⏳ Chargement de la configuration...")
    try:
        config = Config.load()
    except FileNotFoundError:
        print("⚠️  config.yaml introuvable, utilisation des valeurs par défaut")
        config = Config()

    print("⏳ Création du moteur...")
    try:
        engine = LucidEngine(config)
    except Exception as e:
        print(f"❌ CRASH à l'initialisation du moteur: {e}")
        traceback.print_exc()
        return

    # set_loop déclenche l'enregistrement des handlers et le démarrage des agents
    loop = asyncio.get_running_loop()
    print("⏳ Configuration de la boucle asyncio...")
    try:
        engine.set_loop(loop)
    except Exception as e:
        print(f"❌ CRASH à set_loop: {e}")
        traceback.print_exc()
        return

    # Laisser les tâches d'init se terminer
    print("⏳ Attente de l'initialisation des agents (3s)...")
    await asyncio.sleep(3)

    print("✅ Moteur prêt. Début des tests.\n")

    results: list[dict[str, str]] = []

    # ── PROFIL 1 — AVOCAT ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("PROFIL 1 — AVOCAT (Marie, 42 ans)")
    print("=" * 60)
    for cmd in [
        "bonjour",
        "crée un fichier dossier_dupont.txt sur le bureau avec le texte : Audience prévue le 15 avril",
        "résume ce texte : Le tribunal de grande instance a statué en faveur du demandeur",
        "rappelle-moi de préparer le dossier Martin demain à 9h",
        "traduis en anglais : Le contrat est résilié de plein droit",
        "quels sont mes rappels ?",
    ]:
        results.append(await test_command(engine, cmd, "Avocat"))

    # ── PROFIL 2 — DÉVELOPPEUR ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("PROFIL 2 — DÉVELOPPEUR (Lucas, 25 ans)")
    print("=" * 60)
    for cmd in [
        "écris une fonction Python qui trie une liste par ordre alphabétique",
        "explique-moi comment fonctionne asyncio en Python",
        "crée un fichier todo.md sur le bureau avec : # TODO\n- Refactorer le module auth\n- Écrire les tests",
        "planifie le développement d'une API REST en 5 étapes",
        "quelle heure est-il ?",
    ]:
        results.append(await test_command(engine, cmd, "Dev"))

    # ── PROFIL 3 — ÉTUDIANT ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("PROFIL 3 — ÉTUDIANT (Emma, 20 ans)")
    print("=" * 60)
    for cmd in [
        "qu'est-ce que la photosynthèse ?",
        "résume ce chapitre : La Révolution française a débuté en 1789 avec la prise de la Bastille.",
        "traduis en espagnol : Je dois rendre mon devoir pour lundi",
        "fais une recherche sur les causes de la Première Guerre mondiale",
    ]:
        results.append(await test_command(engine, cmd, "Etudiant"))

    # ── PROFIL 4 — ENTREPRENEUR ───────────────────────────────────────
    print("\n" + "=" * 60)
    print("PROFIL 4 — ENTREPRENEUR (Sophie, 35 ans)")
    print("=" * 60)
    for cmd in [
        "planifie le lancement d'un produit en 10 étapes",
        "résume ce mail : Bonjour Sophie, suite à notre réunion je confirme que le partenariat est validé.",
        "traduis en anglais : Notre chiffre d'affaires a augmenté de 30% ce trimestre",
        "donne-moi mon briefing du matin",
    ]:
        results.append(await test_command(engine, cmd, "Entrepreneur"))

    # ── PROFIL 5 — CRÉATIF ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("PROFIL 5 — CRÉATIF (Alex, 28 ans)")
    print("=" * 60)
    for cmd in [
        "écris un poème sur la solitude en 4 vers",
        "écris un post LinkedIn sur l'importance de la créativité en entreprise",
        "crée un fichier idees_projet.txt avec 5 idées de projets créatifs",
    ]:
        results.append(await test_command(engine, cmd, "Creatif"))

    # ── TESTS TRANSVERSAUX ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("TESTS TRANSVERSAUX")
    print("=" * 60)
    for cmd in [
        # Salutations (fast path)
        "salut",
        "merci",
        "au revoir",
        # Mémoire
        "je préfère les réponses courtes",
        # Edge cases
        "",
        "a",
        "Explique-moi en détail comment fonctionne le système nerveux humain en couvrant le système nerveux central et périphérique",
    ]:
        results.append(await test_command(engine, cmd, "Transversal"))

    # ── RAPPORT ───────────────────────────────────────────────────────
    print("\n\n" + "=" * 60)
    print("RAPPORT DE TEST")
    print("=" * 60)

    ok = [r for r in results if r["status"] == "OK"]
    errors = [r for r in results if r["status"] == "ERROR"]
    timeouts = [r for r in results if r["status"] == "TIMEOUT"]

    print(f"\nTotal: {len(results)} tests")
    print(f"  ✅ OK: {len(ok)}")
    print(f"  ❌ Erreurs: {len(errors)}")
    print(f"  ⏰ Timeouts: {len(timeouts)}")
    print(f"  Taux de réussite: {len(ok) / len(results) * 100:.0f}%")

    if errors:
        print(f"\n{'─'*60}")
        print("DÉTAIL DES ERREURS:")
        for e in errors:
            print(f"\n  [{e['profile']}] Commande: {e['command'][:60]}")
            print(f"  Erreur: {e['error']}")
            tb = e.get("traceback", "")
            if tb:
                # Dernières lignes du traceback
                lines = [l for l in tb.strip().split("\n") if l.strip()]
                for line in lines[-4:]:
                    print(f"    {line}")

    if timeouts:
        print(f"\n{'─'*60}")
        print("DÉTAIL DES TIMEOUTS:")
        for t in timeouts:
            print(f"  [{t['profile']}] {t['command'][:60]} — {t['error']}")

    # Sauvegarder le rapport brut
    import json
    report_path = Path("logs/test_results.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nRésultats sauvegardés: {report_path}")

    # ── Arrêt propre ──────────────────────────────────────────────────
    print("\n⏳ Arrêt du moteur...")
    try:
        await engine.stop_async()
    except Exception as e:
        print(f"⚠️  Erreur à l'arrêt: {e}")

    print("✅ Test terminé.")


if __name__ == "__main__":
    asyncio.run(main())
