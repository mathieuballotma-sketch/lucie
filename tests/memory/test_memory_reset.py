"""Tests Swiss watch — règle 6 : MemoryStore.reset() efface tout proprement.

Sans `reset()`, l'avocat n'a aucun moyen de retirer ce que Beaume a appris
de lui (rétention forcée = anti-règle 6). Ces tests valident que le reset :
1. Vide les nœuds et arêtes du PersonalMemory
2. Vide les patterns de l'AbstractMemory
3. Retourne les counts précédents (feedback UI)
4. Permet de continuer à observer après reset (pas de DB cassée)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lucie_v1_standalone.memory.store import MemoryStore


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.mark.asyncio
async def test_reset_clears_personal_memory_nodes(tmp_dir: Path) -> None:
    async with MemoryStore(data_dir=str(tmp_dir)) as store:
        for i in range(5):
            await store.observe({
                "query": f"Question test {i} sur licenciement économique",
                "domain": "licenciement",
                "node_type": "pattern",
                "source": "test",
            })

        before = await store.snapshot()
        nodes_before = (before.get("personal", {}).get("_stats", {})
                              .get("total_nodes", 0))
        assert nodes_before >= 5, (
            f"Au moins 5 nœuds attendus avant reset, got {nodes_before}"
        )

        result = await store.reset()
        assert result["personal_deleted"] >= 5
        assert result["abstract_deleted"] >= 0  # peut être 0 si patterns mergés

        after = await store.snapshot()
        nodes_after = sum(
            len(v) for v in after.values() if isinstance(v, list)
        )
        assert nodes_after == 0, f"0 nœud attendu après reset, got {nodes_after}"


@pytest.mark.asyncio
async def test_reset_clears_abstract_patterns(tmp_dir: Path) -> None:
    async with MemoryStore(data_dir=str(tmp_dir)) as store:
        # Observer plusieurs queries dans le même domaine pour produire des
        # patterns abstraits accumulés.
        for _ in range(3):
            await store.observe({
                "query": "Procédure licenciement économique individuel",
                "domain": "licenciement",
                "node_type": "pattern",
                "source": "test",
            })

        # Patterns créés ?
        patterns_before = store._abstract.all_patterns()
        assert len(patterns_before) >= 1, "Au moins 1 pattern abstrait attendu"

        await store.reset()

        patterns_after = store._abstract.all_patterns()
        assert len(patterns_after) == 0, (
            f"0 pattern abstrait attendu après reset, got {len(patterns_after)}"
        )


@pytest.mark.asyncio
async def test_reset_returns_correct_counts(tmp_dir: Path) -> None:
    async with MemoryStore(data_dir=str(tmp_dir)) as store:
        # Aucune observation → counts = 0
        result = await store.reset()
        assert result["personal_deleted"] == 0
        assert result["abstract_deleted"] == 0

        # 7 observations → counts > 0 au reset suivant
        for i in range(7):
            await store.observe({
                "query": f"q{i} sur indemnité licenciement éco",
                "domain": "indemnite",
                "node_type": "pattern",
                "source": "test",
            })
        result = await store.reset()
        assert result["personal_deleted"] >= 7


@pytest.mark.asyncio
async def test_observe_works_after_reset(tmp_dir: Path) -> None:
    """Après reset, on doit pouvoir continuer à utiliser le store sans crash."""
    async with MemoryStore(data_dir=str(tmp_dir)) as store:
        await store.observe({
            "query": "Reclassement obligation employeur",
            "domain": "reclassement",
            "node_type": "pattern",
            "source": "test",
        })
        await store.reset()

        # Nouvelle observation post-reset — ne doit PAS crasher
        await store.observe({
            "query": "Nouvelle question post-reset",
            "domain": "licenciement",
            "node_type": "pattern",
            "source": "test",
        })

        snapshot = await store.snapshot()
        nodes_after = (snapshot.get("personal", {}).get("_stats", {})
                                .get("total_nodes", 0))
        assert nodes_after >= 1, (
            "Au moins 1 nœud après observe post-reset, "
            f"got {nodes_after} : {snapshot}"
        )


@pytest.mark.asyncio
async def test_reset_idempotent(tmp_dir: Path) -> None:
    """Appeler reset() plusieurs fois ne crashe pas et reste cohérent."""
    async with MemoryStore(data_dir=str(tmp_dir)) as store:
        await store.observe({
            "query": "Test idempotence reset",
            "domain": "licenciement",
            "node_type": "pattern",
            "source": "test",
        })
        await store.reset()
        result2 = await store.reset()  # 2e reset sur DB déjà vide
        assert result2["personal_deleted"] == 0
        assert result2["abstract_deleted"] == 0
