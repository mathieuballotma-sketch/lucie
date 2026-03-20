"""
Tests pour le Graphe de Contexte Personnel (ContextGraph).

Couvre :
- learn + query
- decay (LTD — dépression à long terme)
- reinforce (LTP — potentiation à long terme)
- get_user_profile
- get_context_for
- persistence SQLite (écrire, fermer, rouvrir, vérifier)
"""

import os
import tempfile
import time

import pytest
import pytest_asyncio

from app.memory.context_graph import (
    DEFAULT_CONFIDENCE,
    ContextGraph,
)


# ---------------------------------------------------------------------------
# Fixture : graphe en base temporaire
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def graph():
    """Crée un ContextGraph dans un fichier temporaire et le ferme après le test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    cg = ContextGraph(db_path)
    await cg.initialize()
    yield cg
    await cg.close()

    try:
        os.unlink(db_path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# learn + query
# ---------------------------------------------------------------------------
class TestLearnAndQuery:
    @pytest.mark.asyncio
    async def test_learn_creates_node(self, graph: ContextGraph) -> None:
        node_id = await graph.learn("Python", "skill", source="user")
        assert isinstance(node_id, str)
        assert len(node_id) > 0

    @pytest.mark.asyncio
    async def test_learn_deduplication_reinforces(self, graph: ContextGraph) -> None:
        """Apprendre le même contenu deux fois doit renforcer (LTP), pas créer un doublon."""
        id1 = await graph.learn("Python", "skill", source="user")
        id2 = await graph.learn("Python", "skill", source="user")
        assert id1 == id2

        nodes = await graph.query("Python")
        assert len(nodes) == 1
        # Confiance augmentée (DEFAULT + LTP_BOOST)
        assert nodes[0].confidence > DEFAULT_CONFIDENCE

    @pytest.mark.asyncio
    async def test_learn_different_types_creates_separate_nodes(
        self, graph: ContextGraph
    ) -> None:
        """Même contenu mais types différents → deux nœuds distincts."""
        id_skill = await graph.learn("Python", "skill", source="user")
        id_pref = await graph.learn("Python", "preference", source="user")
        assert id_skill != id_pref

    @pytest.mark.asyncio
    async def test_query_returns_relevant_nodes(self, graph: ContextGraph) -> None:
        await graph.learn("Python asyncio développement", "skill", source="user")
        await graph.learn("Cuisine italienne recettes", "preference", source="user")
        await graph.learn("Projet IA deadline mars", "goal", source="user")

        results = await graph.query("Python développement")
        assert len(results) > 0
        # Le premier résultat doit concerner Python
        assert "python" in results[0].content.lower()

    @pytest.mark.asyncio
    async def test_query_empty_returns_empty(self, graph: ContextGraph) -> None:
        results = await graph.query("")
        assert results == []

    @pytest.mark.asyncio
    async def test_query_no_match_returns_empty(self, graph: ContextGraph) -> None:
        await graph.learn("Python", "skill", source="user")
        results = await graph.query("recette cuisine japonaise")
        assert results == []

    @pytest.mark.asyncio
    async def test_query_top_k_limit(self, graph: ContextGraph) -> None:
        for i in range(10):
            await graph.learn(f"Python skill niveau {i}", "skill", source="user")

        results = await graph.query("Python skill", top_k=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_query_sorted_by_relevance(self, graph: ContextGraph) -> None:
        """Les nœuds avec plus de mots correspondants doivent être mieux classés."""
        await graph.learn("Python développement web asyncio", "skill", source="user")
        await graph.learn("Python script", "skill", source="user")

        results = await graph.query("Python développement asyncio")
        assert len(results) >= 1
        # Le plus pertinent doit être en tête
        assert "développement" in results[0].content or "asyncio" in results[0].content


# ---------------------------------------------------------------------------
# reinforce (LTP)
# ---------------------------------------------------------------------------
class TestReinforce:
    @pytest.mark.asyncio
    async def test_reinforce_increases_confidence(self, graph: ContextGraph) -> None:
        node_id = await graph.learn("Machine learning", "skill", source="user")

        nodes_before = await graph.query("Machine learning")
        conf_before = nodes_before[0].confidence

        await graph.reinforce(node_id)

        nodes_after = await graph.query("Machine learning")
        conf_after = nodes_after[0].confidence

        assert conf_after > conf_before
        assert conf_after <= 1.0

    @pytest.mark.asyncio
    async def test_reinforce_increments_access_count(self, graph: ContextGraph) -> None:
        node_id = await graph.learn("Go programming", "skill", source="user")
        nodes = await graph.query("Go programming")
        access_before = nodes[0].access_count

        await graph.reinforce(node_id)

        nodes = await graph.query("Go programming")
        assert nodes[0].access_count == access_before + 1

    @pytest.mark.asyncio
    async def test_reinforce_caps_at_one(self, graph: ContextGraph) -> None:
        """La confiance ne doit pas dépasser 1.0 même avec beaucoup de renforts."""
        node_id = await graph.learn("Rust", "skill", confidence=0.95, source="user")
        for _ in range(10):
            await graph.reinforce(node_id)

        nodes = await graph.query("Rust")
        assert nodes[0].confidence <= 1.0

    @pytest.mark.asyncio
    async def test_reinforce_nonexistent_node_is_noop(self, graph: ContextGraph) -> None:
        """reinforce() sur un nœud inexistant ne doit pas lever d'exception."""
        await graph.reinforce("nonexistent-id-12345")


# ---------------------------------------------------------------------------
# decay (LTD)
# ---------------------------------------------------------------------------
class TestDecay:
    @pytest.mark.asyncio
    async def test_decay_reduces_confidence(self, graph: ContextGraph) -> None:
        """Un nœud avec decay_rate > 0 doit perdre de la confiance après decay()."""
        # decay_rate=0.1 → perd 0.1 * 1h = 0.1 sur 1 heure.
        # confidence initiale : 0.5 → après decay : ≈ 0.4 (reste > 0.1, pas archivé).
        node_id = await graph.learn(
            "Vieille info obsolète",
            "pattern",
            confidence=0.5,
            decay_rate=0.1,  # 0.1 point par heure
            source="test",
        )

        # Simuler que le nœud n'a pas été accédé depuis 1 heure
        conn = await graph._get_conn()
        one_hour_ago = time.time() - 3600
        await conn.execute(
            "UPDATE context_nodes SET updated_at=? WHERE id=?",
            (one_hour_ago, node_id),
        )
        await conn.commit()

        archived = await graph.decay()
        # Le nœud perd 0.1 * 1h = 0.1 → confidence ≈ 0.4, toujours actif
        nodes = await graph.query("Vieille info")
        assert len(nodes) > 0
        assert nodes[0].confidence < 0.5

        _ = archived  # peut être 0 ici (nœud toujours actif), c'est normal

    @pytest.mark.asyncio
    async def test_decay_archives_low_confidence_nodes(
        self, graph: ContextGraph
    ) -> None:
        """Un nœud avec confiance très basse doit être archivé par decay()."""
        node_id = await graph.learn(
            "Info très ancienne à archiver",
            "pattern",
            confidence=0.15,   # juste au-dessus du seuil
            decay_rate=100.0,  # déclin très rapide
            source="test",
        )

        # Forcer updated_at loin dans le passé
        conn = await graph._get_conn()
        very_old = time.time() - 7200  # 2h dans le passé
        await conn.execute(
            "UPDATE context_nodes SET updated_at=? WHERE id=?",
            (very_old, node_id),
        )
        await conn.commit()

        archived_count = await graph.decay()
        assert archived_count >= 1

        # Le nœud ne doit plus apparaître dans les résultats
        nodes = await graph.query("Info très ancienne")
        assert all(n.id != node_id for n in nodes)

    @pytest.mark.asyncio
    async def test_decay_leaves_fresh_nodes_untouched(
        self, graph: ContextGraph
    ) -> None:
        """Un nœud récemment accédé ne doit pas être archivé."""
        await graph.learn(
            "Compétence active utilisée récemment",
            "skill",
            confidence=0.8,
            decay_rate=0.01,
            source="test",
        )

        archived = await graph.decay()
        assert archived == 0

        nodes = await graph.query("Compétence active")
        assert len(nodes) == 1

    @pytest.mark.asyncio
    async def test_decay_returns_archive_count(self, graph: ContextGraph) -> None:
        """decay() doit retourner le nombre de nœuds archivés."""
        result = await graph.decay()
        assert isinstance(result, int)
        assert result >= 0


# ---------------------------------------------------------------------------
# get_user_profile
# ---------------------------------------------------------------------------
class TestGetUserProfile:
    @pytest.mark.asyncio
    async def test_profile_contains_all_types(self, graph: ContextGraph) -> None:
        await graph.learn("Python", "skill", source="user")
        await graph.learn("Communication directe", "preference", source="user")
        await graph.learn("Lancer agent IA d'ici fin mars", "goal", source="user")
        await graph.learn("Alice chef de projet", "relation", source="user")
        await graph.learn("Travaille souvent le soir", "pattern", source="user")

        profile = await graph.get_user_profile()

        assert "skill" in profile
        assert "preference" in profile
        assert "goal" in profile
        assert "relation" in profile
        assert "pattern" in profile
        assert "_stats" in profile

    @pytest.mark.asyncio
    async def test_profile_stats_total(self, graph: ContextGraph) -> None:
        await graph.learn("Python", "skill", source="user")
        await graph.learn("Rust", "skill", source="user")

        profile = await graph.get_user_profile()
        total = profile["_stats"]["total_nodes"]
        assert total == 2

    @pytest.mark.asyncio
    async def test_profile_sorted_by_confidence(self, graph: ContextGraph) -> None:
        """Les nœuds doivent être triés par confiance décroissante."""
        await graph.learn("Python", "skill", confidence=0.9, source="user")
        await graph.learn("COBOL", "skill", confidence=0.2, source="user")

        profile = await graph.get_user_profile()
        skills = profile["skill"]
        assert len(skills) == 2
        assert skills[0]["confidence"] >= skills[1]["confidence"]

    @pytest.mark.asyncio
    async def test_profile_excludes_archived_nodes(self, graph: ContextGraph) -> None:
        """Les nœuds archivés ne doivent pas apparaître dans le profil."""
        node_id = await graph.learn(
            "Info archivée", "pattern", confidence=0.15, decay_rate=100.0, source="test"
        )
        # Forcer l'archivage
        conn = await graph._get_conn()
        await conn.execute(
            "UPDATE context_nodes SET archived=1 WHERE id=?", (node_id,)
        )
        await conn.commit()

        profile = await graph.get_user_profile()
        all_contents = [
            item["content"]
            for items in [profile[t] for t in ["skill", "preference", "goal", "relation", "pattern"]]
            for item in items
        ]
        assert "Info archivée" not in all_contents

    @pytest.mark.asyncio
    async def test_profile_empty_when_no_nodes(self, graph: ContextGraph) -> None:
        profile = await graph.get_user_profile()
        assert profile["_stats"]["total_nodes"] == 0
        for t in ["skill", "preference", "goal", "relation", "pattern"]:
            assert profile[t] == []


# ---------------------------------------------------------------------------
# get_context_for
# ---------------------------------------------------------------------------
class TestGetContextFor:
    @pytest.mark.asyncio
    async def test_context_returns_relevant_text(self, graph: ContextGraph) -> None:
        await graph.learn("Expert Python asyncio", "skill", source="user")
        await graph.learn("Aime les pizzas", "preference", source="user")

        context = await graph.get_context_for("développer une API Python")
        assert "Python" in context
        assert "[SKILL]" in context

    @pytest.mark.asyncio
    async def test_context_empty_when_no_match(self, graph: ContextGraph) -> None:
        await graph.learn("Python", "skill", source="user")
        context = await graph.get_context_for("recette lasagnes italiennes")
        assert context == ""

    @pytest.mark.asyncio
    async def test_context_includes_confidence_label(self, graph: ContextGraph) -> None:
        await graph.learn("Machine learning avancé", "skill", confidence=0.8, source="user")
        context = await graph.get_context_for("machine learning")
        assert "haute" in context or "moyenne" in context or "faible" in context

    @pytest.mark.asyncio
    async def test_context_top_k_limits_output(self, graph: ContextGraph) -> None:
        for i in range(10):
            await graph.learn(f"Compétence Python niveau {i}", "skill", source="user")

        context = await graph.get_context_for("Python", top_k=2)
        lines = [line for line in context.split("\n") if line.strip()]
        assert len(lines) <= 2


# ---------------------------------------------------------------------------
# Persistence SQLite
# ---------------------------------------------------------------------------
class TestPersistence:
    @pytest.mark.asyncio
    async def test_data_persists_after_close_and_reopen(self) -> None:
        """Écrire des données, fermer, rouvrir, vérifier que les données sont là."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            # Phase 1 : écriture
            cg1 = ContextGraph(db_path)
            await cg1.initialize()
            node_id = await cg1.learn("Persisted skill", "skill", source="test")
            await cg1.close()

            # Phase 2 : relecture
            cg2 = ContextGraph(db_path)
            await cg2.initialize()
            nodes = await cg2.query("Persisted skill")
            await cg2.close()

            assert len(nodes) == 1
            assert nodes[0].id == node_id
            assert nodes[0].content == "Persisted skill"
            assert nodes[0].node_type == "skill"
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass

    @pytest.mark.asyncio
    async def test_confidence_persists(self) -> None:
        """La confiance mise à jour doit être restaurée fidèlement."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            cg1 = ContextGraph(db_path)
            await cg1.initialize()
            node_id = await cg1.learn("Rust", "skill", confidence=0.3, source="test")
            await cg1.reinforce(node_id)
            await cg1.reinforce(node_id)
            nodes1 = await cg1.query("Rust")
            expected_confidence = nodes1[0].confidence
            await cg1.close()

            cg2 = ContextGraph(db_path)
            await cg2.initialize()
            nodes2 = await cg2.query("Rust")
            await cg2.close()

            assert len(nodes2) == 1
            assert abs(nodes2[0].confidence - expected_confidence) < 0.001
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass

    @pytest.mark.asyncio
    async def test_edges_persist(self) -> None:
        """Les arêtes doivent être restaurées après fermeture/réouverture."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            cg1 = ContextGraph(db_path)
            await cg1.initialize()
            id_a = await cg1.learn("Python", "skill", source="test")
            id_b = await cg1.learn("FastAPI", "skill", source="test")
            await cg1.add_edge(id_a, id_b, "related_to", weight=0.9)
            await cg1.close()

            cg2 = ContextGraph(db_path)
            await cg2.initialize()
            edges = await cg2.get_edges(id_a)
            await cg2.close()

            assert len(edges) == 1
            assert edges[0].source_id == id_a
            assert edges[0].target_id == id_b
            assert edges[0].relation == "related_to"
            assert abs(edges[0].weight - 0.9) < 0.001
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Le graphe doit fonctionner comme context manager async."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            async with ContextGraph(db_path) as cg:
                node_id = await cg.learn("Context manager test", "skill", source="test")
                nodes = await cg.query("Context manager")
                assert len(nodes) == 1
                assert nodes[0].id == node_id
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass
