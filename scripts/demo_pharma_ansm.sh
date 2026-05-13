#!/usr/bin/env bash
# Démo Sprint G-1 étape 1 — preuve fonctionnelle de la généricité Beaume.
#
# Lance Beaume sur le corpus pharma ANSM (additif au chemin droit social).
# Aucune modification du pipeline existant — c'est une route parallèle.
#
# Usage :
#   bash scripts/demo_pharma_ansm.sh
#
# Prérequis :
#   - Python 3.11+ avec les dépendances du repo installées
#   - Pas besoin d'Ollama (--no-llm force le mode déterministe)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "============================================================"
echo "DÉMO Sprint G-1 étape 1 — Beaume sur corpus alternatif"
echo "============================================================"
echo
echo "[1/3] Question dans le scope ANSM (publicité grand public)"
echo "------------------------------------------------------------"
python3 -m lucie_v1_standalone \
  --corpus fr_pharma_ansm \
  --no-llm \
  --quiet \
  "puis-je faire de la publicité directe pour un médicament listé II ?"

echo
echo "[2/3] Question hors-scope ANSM (fiscal)"
echo "------------------------------------------------------------"
python3 -m lucie_v1_standalone \
  --corpus fr_pharma_ansm \
  --no-llm \
  --quiet \
  "comment optimiser la TVA sur les ventes pharmaceutiques ?"

echo
echo "[3/3] Question hors-scope ANSM (brevet)"
echo "------------------------------------------------------------"
python3 -m lucie_v1_standalone \
  --corpus fr_pharma_ansm \
  --no-llm \
  --quiet \
  "comment déposer un brevet sur ma molécule innovante ?"

echo
echo "============================================================"
echo "Démo terminée. Le pipeline droit social par défaut reste"
echo "inchangé : 'python3 -m lucie_v1_standalone \"<question>\"'"
echo "sans --corpus utilise toujours le moteur historique."
echo "============================================================"
