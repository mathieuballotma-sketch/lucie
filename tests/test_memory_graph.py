"""Tests de persistance SQLite pour MemoryGraph."""

import tempfile


def test_memory_graph_persistence():
    """Vérifie que les liens survivent à la recréation du graphe."""
    from app.memory.memory_graph import MemoryGraph

    with tempfile.TemporaryDirectory() as d:
        db = f"{d}/test.db"
        mg = MemoryGraph(db_path=db)
        mg.link("python", "code", 2.0)
        mg.strengthen("python", "code")
        stats1 = mg.get_stats()

        # Recréer depuis la même DB
        mg2 = MemoryGraph(db_path=db)
        stats2 = mg2.get_stats()
        assert stats2["concepts"] == stats1["concepts"]
        assert mg2.weights.get("python:code", 0) > 0


def test_memory_graph_ram_fallback():
    """Vérifie le fallback RAM si la DB est inaccessible."""
    from app.memory.memory_graph import MemoryGraph

    mg = MemoryGraph(db_path="/nonexistent/path/db.sqlite")
    mg.link("a", "b", 1.0)
    assert "b" in mg.graph["a"]
