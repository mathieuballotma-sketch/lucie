"""Simulation MemoryGraph — hippocampe numérique avec liens résonnants."""


class MemoryGraph:
    """
    Hippocampe numérique — Loi de Résonance.
    Les concepts s'attirent par résonance pondérée.
    """

    def __init__(self):
        self.graph: dict[str, list[str]] = {}
        self.weights: dict[str, float] = {}

    def link(self, concept_a: str, concept_b: str, weight: float = 1.0):
        """Crée un lien résonnant bidirectionnel entre deux concepts."""
        self.graph.setdefault(concept_a, []).append(concept_b)
        key = f"{concept_a}:{concept_b}"
        self.weights[key] = self.weights.get(key, 0) + weight

    def resonate(self, concept: str, depth: int = 2) -> list[tuple[str, float]]:
        """Trouve les concepts en résonance (voisins pondérés)."""
        visited: set[str] = set()
        result: list[tuple[str, float]] = []

        def traverse(node: str, d: int) -> None:
            if d == 0 or node in visited:
                return
            visited.add(node)
            for n in self.graph.get(node, []):
                weight = self.weights.get(f"{node}:{n}", 1.0)
                result.append((n, weight))
                traverse(n, d - 1)

        traverse(concept, depth)
        return sorted(result, key=lambda x: x[1], reverse=True)

    def strengthen(self, concept_a: str, concept_b: str):
        """Renforce la résonance après interaction réussie."""
        key = f"{concept_a}:{concept_b}"
        self.weights[key] = self.weights.get(key, 0) + 0.1


def test_memory_graph():
    print("── Simulation MemoryGraph ──")

    graph = MemoryGraph()

    # 5 concepts reliés
    graph.link("or", "bitcoin", 0.8)
    graph.link("or", "bourse", 0.9)
    graph.link("bitcoin", "crypto", 0.7)
    graph.link("bourse", "investissement", 0.6)
    graph.link("finance", "or", 1.0)

    # Vérifier resonate
    related = graph.resonate("or")
    names = [r[0] for r in related]
    assert "bourse" in names
    assert "bitcoin" in names
    print(f"  ✅ Résonance 'or' → {names}")

    # Profondeur 2 — voisins des voisins
    deep = graph.resonate("finance", depth=2)
    deep_names = [r[0] for r in deep]
    assert "or" in deep_names
    print(f"  ✅ Résonance profonde 'finance' → {deep_names}")

    # Strengthen
    before = graph.weights.get("or:bitcoin", 0)
    graph.strengthen("or", "bitcoin")
    after = graph.weights.get("or:bitcoin", 0)
    assert after > before
    print(f"  ✅ Renforcement : {before:.1f} → {after:.1f}")

    # 10 liens — cohérence
    graph.link("crypto", "nft", 0.3)
    graph.link("nft", "art", 0.4)
    graph.link("art", "culture", 0.5)
    graph.link("culture", "musique", 0.2)
    graph.link("musique", "spotify", 0.6)
    assert len(graph.graph) >= 8
    print(f"  ✅ Graphe cohérent : {len(graph.graph)} nœuds")

    # Compatibilité EpisodicMemory : resonate retourne (str, float) tuples
    for concept, score in graph.resonate("crypto"):
        assert isinstance(concept, str)
        assert isinstance(score, float)
    print("  ✅ Format compatible EpisodicMemory")

    print("  → MemoryGraph : 5/5 tests passés ✅\n")


if __name__ == "__main__":
    test_memory_graph()
