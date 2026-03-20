"""
Simulation ContextWave — vérifie la compatibilité avec les composants existants.
Teste l'API réelle de ContextWave (frozen dataclass immuable).

Lance : PYTHONPATH=. python3 tests/simulation/test_context_wave.py
"""

import time
import sys
sys.path.insert(0, ".")

from app.brain.cortex.context_wave import ContextWave


def test_creation():
    """Test 1 — Création basique."""
    ctx = ContextWave.create("test query", budget=10.0)
    assert ctx.query == "test query"
    assert ctx.budget == 10.0
    assert ctx.remaining() > 9.0
    assert ctx.chain_step == 0
    assert ctx.signals is not None


def test_budget_timeout():
    """Test 2 — Budget timeout partagé."""
    ctx = ContextWave.create("query", budget=2.0)
    assert ctx.remaining() <= 2.0
    assert ctx.remaining() > 1.9
    assert not ctx.is_expired()

    # Simuler passage du temps
    time.sleep(0.1)
    remaining_after = ctx.remaining()
    assert remaining_after < 2.0


def test_enrichissement():
    """Test 3 — Onde immuable — toute modification crée une nouvelle onde."""
    ctx = ContextWave.create("cours de l'or")

    # ContextWave est frozen — next_wave() crée une nouvelle onde
    new_ctx = ctx.next_wave(memory=("prix or: 2300$ l'once",))
    assert len(new_ctx.memory) == 1
    assert new_ctx.chain_step == 1
    # L'original est inchangé
    assert len(ctx.memory) == 0
    assert ctx.chain_step == 0


def test_enriched_system():
    """Test 4 — Construction du contexte enrichi."""
    ctx = ContextWave.create("question")
    new_ctx = ctx.next_wave(memory=("Souvenir important",))

    enriched = new_ctx.get_enriched_system()
    assert enriched is not None
    assert "question" in enriched
    assert "Souvenir important" in enriched

    # Appeler une 2ème fois — même résultat
    enriched2 = new_ctx.get_enriched_system()
    assert enriched == enriched2


def test_effective_timeout():
    """Test 5 — Timeout adapté au budget restant."""
    ctx = ContextWave.create("query", budget=5.0)

    # Timeout par défaut 8s mais budget 5s → retourne 5s max
    assert ctx.get_effective_timeout(8.0) <= 5.0

    # Timeout demandé 2s avec budget 5s → retourne 2s
    assert ctx.get_effective_timeout(2.0) == 2.0


def test_next_wave():
    """Test 6 — Propagation et chaînage des ondes."""
    ctx = ContextWave.create("question")
    assert ctx.chain_step == 0

    next_ctx = ctx.next_wave(memory=("réponse étape 1",))
    assert next_ctx.chain_step == 1
    assert next_ctx.query == ctx.query
    assert next_ctx.budget == ctx.budget
    assert next_ctx.parent_wave is ctx

    # Chaîne de 3 étapes
    ctx3 = next_ctx.next_wave()
    assert ctx3.chain_step == 2


def test_string_compatibility():
    """Test 7 — ctx.query est un str compatible avec les composants existants."""
    ctx = ContextWave.create("ouvre safari")

    # Les composants existants passent query: str
    assert isinstance(ctx.query, str)
    assert ctx.query == "ouvre safari"
    assert ctx.query.lower() == "ouvre safari"
    assert "safari" in ctx.query


def test_compatibility_signatures():
    """Test 8 — Vérifier la compatibilité avec les signatures existantes."""
    ctx = ContextWave.create("test", budget=30.0)

    # think(query: str, system_prompt, allow_web_search) → ctx.query est str
    query = ctx.query
    assert isinstance(query, str)

    # get_effective_timeout() pour les asyncio.wait_for
    timeout = ctx.get_effective_timeout(30.0)
    assert 0 < timeout <= 30.0

    # get_enriched_system() pour enrichir les prompts
    enriched = ctx.get_enriched_system()
    assert isinstance(enriched, str)

    # signals contient les fréquences Thalamus
    assert ctx.signals is not None
    assert "frequencies" in ctx.signals


def test_full_pipeline_mock():
    """Test 9 — Simulation pipeline complet sans Ollama."""
    ctx = ContextWave.create(
        "recherche le cours de l'or",
        budget=30.0,
    )

    assert not ctx.is_expired()
    timeout = ctx.get_effective_timeout(30.0)
    assert timeout > 0

    # Étape 1 : RAG enrichit l'onde
    ctx_with_rag = ctx.next_wave(memory=("prix or: 2300$ l'once en mars 2026",))
    assert len(ctx_with_rag.memory) == 1
    assert ctx_with_rag.chain_step == 1

    # Étape 2 : Enrichissement du prompt
    enriched = ctx_with_rag.get_enriched_system()
    assert "2300$" in enriched

    # Étape 3 : Timeout effectif
    remaining = ctx.remaining()
    assert remaining > 0
    assert ctx_with_rag.remaining() > 0

    # Étape 4 : Chaîne finale
    ctx_final = ctx_with_rag.next_wave()
    assert ctx_final.chain_step == 2
    assert ctx_final.parent_wave is ctx_with_rag
    assert not ctx_final.is_expired()


if __name__ == "__main__":
    print("=" * 50)
    print("SIMULATION CONTEXTWAVE — LUCIE")
    print("=" * 50)
    print()

    test_creation()
    print("✅ Test 1 — Création : OK")
    test_budget_timeout()
    print("✅ Test 2 — Budget timeout : OK")
    test_enrichissement()
    print("✅ Test 3 — Enrichissement : OK")
    test_enriched_system()
    print("✅ Test 4 — Prompt enrichi : OK")
    test_effective_timeout()
    print("✅ Test 5 — Timeout effectif : OK")
    test_next_wave()
    print("✅ Test 6 — Propagation : OK")
    test_string_compatibility()
    print("✅ Test 7 — Compatibilité string : OK")
    test_compatibility_signatures()
    print("✅ Test 8 — Compatibilité signatures : OK")
    test_full_pipeline_mock()
    print("✅ Test 9 — Pipeline complet (mock) : OK")

    print()
    print("=" * 50)
    print("9/9 TESTS PASSÉS ✅")
    print("=" * 50)
