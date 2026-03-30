"""
Benchmark de classification mail — SmartMailAgent.

Teste la qualité de classification sur 100 mails réalistes d'avocats/notaires
en français. Utilise le même prompt que l'agent en production.

Seuil requis : 85% d'accuracy globale (THRESHOLD = 0.85).

Usage :
    PYTHONPATH=. python3 tests/benchmark_mail_classification.py
    PYTHONPATH=. python3 tests/benchmark_mail_classification.py qwen2.5:7b
"""

import asyncio
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Import du prompt de classification depuis SmartMailAgent ─────────────────
# On réutilise exactement le même prompt qu'en production pour que le benchmark
# mesure les vraies performances, pas une variante artificielle.
from app.agents.smart_mail_agent import _CLASSIFICATION_PROMPT

# ── Configuration ────────────────────────────────────────────────────────────

# Chemin vers le dataset de 100 mails
DATASET_PATH = Path(__file__).parent / "data" / "mail_benchmark.json"

# Endpoint Ollama local (identique à l'agent)
OLLAMA_URL = "http://localhost:11434/api/generate"

# Modèle par défaut : le modèle "speed" utilisé par SmartMailAgent → qwen2.5:3b
# Peut être surchargé via argument CLI : python3 benchmark.py qwen2.5:7b
DEFAULT_MODEL = "qwen2.5:3b"

# Seuil d'accuracy minimale pour valider le benchmark (PASS/FAIL)
THRESHOLD = 0.85

# Nombre d'appels Ollama simultanés (cohérent avec le sémaphore de SmartMailAgent)
MAX_CONCURRENT = 3

# Niveaux de classification (ordre décroissant de priorité)
LEVELS = ["CRITIQUE", "URGENT", "NORMAL", "BASSE"]


# ── Mapping type+priorité → niveau de classification ────────────────────────

def map_to_level(result: Dict[str, Any]) -> str:
    """
    Convertit la classification LLM (champs type + priorite) en niveau
    CRITIQUE / URGENT / NORMAL / BASSE.

    Règles (cohérentes avec la logique de _act_on_classification) :
    - spam ou pub → toujours BASSE (ignorés silencieusement par l'agent)
    - priorite <= 1 → BASSE (pas assez important pour traiter)
    - priorite >= 5 → CRITIQUE (action immédiate, délai très court)
    - type=="urgent" OU priorite >= 4 → URGENT
    - sinon → NORMAL (pro/personnel, priorité 2-3)
    """
    mail_type = str(result.get("type", "pro")).lower().strip()
    try:
        priorite = int(result.get("priorite", 3))
    except (ValueError, TypeError):
        priorite = 3

    # Spam et pub : toujours ignoré, quelle que soit la priorité déclarée
    if mail_type in ("spam", "pub"):
        return "BASSE"

    # Priorité minimale → BASSE
    if priorite <= 1:
        return "BASSE"

    # Priorité maximale → CRITIQUE (audience demain, délai expirant)
    if priorite >= 5:
        return "CRITIQUE"

    # Type urgent OU haute priorité → URGENT
    if mail_type == "urgent" or priorite >= 4:
        return "URGENT"

    # Par défaut : traitement normal (pro / personnel, priorité 2 ou 3)
    return "NORMAL"


# ── Parser JSON (logique identique à SmartMailAgent._parse_classification) ───

def parse_classification(response: str) -> Dict[str, Any]:
    """
    Extrait le JSON de classification depuis la réponse brute du LLM.
    Identique à SmartMailAgent._parse_classification pour cohérence.
    """
    try:
        # Cherche le premier objet JSON dans la réponse
        match = re.search(r"\{[^}]+\}", response, re.DOTALL)
        if match:
            result: Dict[str, Any] = json.loads(match.group())
            return result
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback : mail professionnel de priorité moyenne (ne doit pas survenir souvent)
    return {
        "type": "pro",
        "priorite": 3,
        "action": "lire",
        "resume": "parsing échoué",
        "contient_reunion": False,
        "contient_deadline": False,
    }


# ── Appel Ollama (synchrone, exécuté dans un thread) ────────────────────────

def _call_ollama_sync(model: str, prompt: str) -> Optional[str]:
    """
    Appel synchrone à l'API Ollama /api/generate.
    Tournera dans un ThreadPoolExecutor pour ne pas bloquer la boucle asyncio.
    Retourne le texte de la réponse, ou None en cas d'erreur.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,   # Faible température pour classification déterministe
            "num_predict": 200,   # Le JSON de classification est court
            "num_ctx": 2048,
        },
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body: Dict[str, Any] = json.loads(resp.read())
            return str(body.get("response", ""))
    except urllib.error.URLError:
        return None
    except Exception:
        return None


# ── Classification d'un mail ─────────────────────────────────────────────────

async def classify_mail(
    mail: Dict[str, str],
    model: str,
    executor: ThreadPoolExecutor,
) -> str:
    """
    Classifie un mail via Ollama et retourne le niveau CRITIQUE/URGENT/NORMAL/BASSE.
    Utilise le même prompt que SmartMailAgent en production.
    """
    sender = mail.get("sender", "inconnu")
    subject = mail.get("subject", "(sans sujet)")
    body = mail.get("body", "")

    # Même prompt qu'en production (limité à 500 caractères de corps)
    prompt = (
        "Tu es un classificateur de mails. JSON uniquement.\n\n"
        + _CLASSIFICATION_PROMPT.format(
            sender=sender,
            subject=subject,
            body=body[:500],
        )
    )

    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(executor, _call_ollama_sync, model, prompt)

    if response is None:
        # Ollama non disponible ou erreur réseau → fallback neutre
        return "NORMAL"

    classification = parse_classification(response)
    return map_to_level(classification)


# ── Calcul des métriques ──────────────────────────────────────────────────────

def compute_metrics(
    results: List[Tuple[str, str]],
) -> Dict[str, Any]:
    """
    Calcule les métriques de classification :
    - Accuracy globale
    - Precision, Recall, F1 par niveau
    - Matrice de confusion (lignes = réel, colonnes = prédit)
    """
    total = len(results)
    correct = sum(1 for expected, predicted in results if expected == predicted)

    # Matrice de confusion : confusion[niveau_réel][niveau_prédit] = nombre
    confusion: Dict[str, Dict[str, int]] = {
        level: {other: 0 for other in LEVELS} for level in LEVELS
    }
    for expected, predicted in results:
        if expected in LEVELS and predicted in LEVELS:
            confusion[expected][predicted] += 1

    # Métriques par niveau (precision, recall, F1)
    per_level: Dict[str, Dict[str, Any]] = {}
    for level in LEVELS:
        tp = confusion[level][level]
        # Faux positifs : autres niveaux classifiés comme ce niveau
        fp = sum(confusion[other][level] for other in LEVELS if other != level)
        # Faux négatifs : ce niveau classifié comme autre chose
        fn = sum(confusion[level][other] for other in LEVELS if other != level)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        per_level[level] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "support": tp + fn,  # Nombre réel de mails de ce niveau dans le dataset
        }

    return {
        "accuracy": correct / total if total > 0 else 0.0,
        "correct": correct,
        "total": total,
        "per_level": per_level,
        "confusion": confusion,
    }


# ── Rapport de résultats ──────────────────────────────────────────────────────

def print_report(metrics: Dict[str, Any], duration: float, model: str) -> None:
    """Affiche le rapport complet du benchmark avec PASS/FAIL."""
    accuracy = metrics["accuracy"]
    status = "PASS" if accuracy >= THRESHOLD else "FAIL"
    sep = "=" * 68

    print()
    print(sep)
    print("  BENCHMARK CLASSIFICATION MAIL — SmartMailAgent")
    print(sep)
    print(f"  Modèle   : {model}")
    print(f"  Dataset  : {metrics['total']} mails")
    print(f"  Durée    : {duration:.1f}s")
    print(f"  Accuracy : {accuracy:.1%}   (seuil requis : {THRESHOLD:.0%})")
    print()

    # Métriques par niveau
    print("  Métriques par niveau :")
    header = (
        f"  {'Niveau':<10}  {'Support':>7}  "
        f"{'Precision':>10}  {'Recall':>8}  {'F1':>8}"
    )
    print(header)
    print("  " + "-" * 56)
    for level in LEVELS:
        m = metrics["per_level"][level]
        print(
            f"  {level:<10}  {m['support']:>7}  "
            f"{m['precision']:>9.1%}  {m['recall']:>7.1%}  {m['f1']:>7.1%}"
        )

    # Matrice de confusion
    print()
    print("  Matrice de confusion (lignes=réel, colonnes=prédit) :")
    col_w = 10
    print("  " + " " * 12 + "".join(f"{l:>{col_w}}" for l in LEVELS))
    print("  " + "-" * (12 + col_w * len(LEVELS)))
    for expected in LEVELS:
        row = f"  {expected:<12}"
        for predicted in LEVELS:
            count = metrics["confusion"][expected][predicted]
            # Marquer la diagonale (classifications correctes)
            cell = f"[{count:>3}]" if expected == predicted else f" {count:>3} "
            row += f"{cell:>{col_w}}"
        print(row)

    # Erreurs de classification
    print()
    print("  Erreurs notables (niveau réel → niveau prédit) :")
    erreurs_affichees = 0
    for expected in LEVELS:
        for predicted in LEVELS:
            if expected != predicted:
                count = metrics["confusion"][expected][predicted]
                if count > 0:
                    print(f"    {expected} → {predicted} : {count} mail(s)")
                    erreurs_affichees += 1
    if erreurs_affichees == 0:
        print("    Aucune erreur !")

    # Résultat final PASS / FAIL
    print()
    print(sep)
    if accuracy >= THRESHOLD:
        print(f"  RESULTAT : {status}  —  Accuracy {accuracy:.1%} >= {THRESHOLD:.0%}")
    else:
        gap = THRESHOLD - accuracy
        print(
            f"  RESULTAT : {status}  —  Accuracy {accuracy:.1%} < {THRESHOLD:.0%}"
            f"  (manque {gap:.1%})"
        )
    print(sep)
    print()


# ── Vérification Ollama ───────────────────────────────────────────────────────

def check_ollama_available() -> bool:
    """Vérifie qu'Ollama est accessible sur localhost:11434."""
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags", method="GET"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def check_model_available(model: str) -> bool:
    """Vérifie que le modèle demandé est disponible dans Ollama."""
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags", method="GET"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body: Dict[str, Any] = json.loads(resp.read())
            models = body.get("models", [])
            return any(m.get("name", "").startswith(model) for m in models)
    except Exception:
        return False


# ── Boucle principale du benchmark ───────────────────────────────────────────

async def run_benchmark(model: str) -> int:
    """
    Lance le benchmark complet.

    Retourne :
        0 → PASS (accuracy >= 85%)
        1 → FAIL (accuracy < 85%)
        2 → Ollama non disponible
        3 → Dataset introuvable ou invalide
    """
    # 1. Vérification Ollama
    print(f"\n📡 Vérification Ollama sur localhost:11434...")
    if not check_ollama_available():
        print("  Ollama non disponible. Démarrer Ollama puis relancer.")
        print("  Commande : ollama serve")
        return 2

    if not check_model_available(model):
        print(f"  Modèle '{model}' non trouvé dans Ollama.")
        print(f"  Commande pour l'installer : ollama pull {model}")
        return 2

    print(f"  Ollama OK — modèle '{model}' disponible.")

    # 2. Chargement du dataset
    if not DATASET_PATH.exists():
        print(f"  Dataset introuvable : {DATASET_PATH}")
        return 3

    with DATASET_PATH.open(encoding="utf-8") as f:
        dataset: Dict[str, Any] = json.load(f)

    mails: List[Dict[str, str]] = dataset.get("mails", [])
    if not mails:
        print("  Dataset vide.")
        return 3

    distribution = dataset.get("distribution", {})
    print(f"\n📊 Dataset : {len(mails)} mails")
    for level, count in distribution.items():
        print(f"   {level:<10} : {count}")

    # 3. Classification de tous les mails
    print(f"\n🔄 Classification en cours via {model}...")
    print("   (3 appels simultanés, ~30s par mail selon le matériel)")
    print()

    start = time.time()
    results: List[Tuple[str, str]] = []
    errors = 0

    # Sémaphore pour limiter les appels Ollama simultanés (comme dans l'agent)
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def classify_with_progress(
        mail: Dict[str, str],
        index: int,
        total: int,
        executor: ThreadPoolExecutor,
    ) -> Tuple[str, str]:
        """Classifie un mail avec sémaphore et affichage de progression."""
        nonlocal errors
        expected = mail.get("expected_level", "NORMAL")
        async with sem:
            try:
                predicted = await classify_mail(mail, model, executor)
            except Exception as e:
                errors += 1
                predicted = "NORMAL"
                print(f"   ⚠ Erreur mail #{mail.get('id', '?')} : {e}")
        return (expected, predicted)

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
        tasks = [
            classify_with_progress(mail, i + 1, len(mails), executor)
            for i, mail in enumerate(mails)
        ]
        total_tasks = len(tasks)
        done_count = 0

        for coro in asyncio.as_completed(tasks):
            pair = await coro
            results.append(pair)
            done_count += 1
            # Affichage de progression toutes les 10 classifications
            if done_count % 10 == 0 or done_count == total_tasks:
                elapsed = time.time() - start
                rate = done_count / elapsed if elapsed > 0 else 0
                remaining = (total_tasks - done_count) / rate if rate > 0 else 0
                print(
                    f"   [{done_count:>3}/{total_tasks}]  "
                    f"{elapsed:.0f}s écoulées  "
                    f"~{remaining:.0f}s restantes",
                    end="\r",
                    flush=True,
                )

    duration = time.time() - start
    print()  # Fin de la ligne de progression

    if errors > 0:
        print(f"   ⚠ {errors} erreur(s) lors de la classification (retombée sur NORMAL)")

    # 4. Calcul des métriques et affichage du rapport
    metrics = compute_metrics(results)
    print_report(metrics, duration, model)

    return 0 if metrics["accuracy"] >= THRESHOLD else 1


# ── Point d'entrée CLI ────────────────────────────────────────────────────────

def main() -> None:
    """
    Point d'entrée du benchmark.
    Argument optionnel : nom du modèle Ollama à utiliser.
    Exemple : python3 tests/benchmark_mail_classification.py qwen2.5:7b
    """
    model = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    print(f"Benchmark SmartMailAgent — modèle : {model}")
    exit_code = asyncio.run(run_benchmark(model))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
