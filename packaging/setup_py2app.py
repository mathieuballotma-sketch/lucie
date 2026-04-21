"""
Config py2app pour Lucie — packaging macOS natif.

Usage :
    cd <racine du repo>
    python3 packaging/setup_py2app.py py2app

Ne PAS confondre avec le `setup.py` à la racine du repo (utilitaire d'init env,
non lié au build). Ce fichier-ci est appelé par `packaging/build.sh`.

Tree-shaking agressif : on exclut torch / faster-whisper / onnxruntime /
ctranslate2 / scipy du bundle (dictée inactive en v1, cible DMG < 500 MB).
"""

from pathlib import Path

from setuptools import setup

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_ENTRY = str(REPO_ROOT / "main_hud.py")

# Ressources statiques à embarquer dans Lucie.app/Contents/Resources/.
# La base Légifrance (~3 GB) n'est PAS incluse — elle est téléchargée au
# premier lancement par scripts/legifrance_sync.py (cf. plan packaging).
DATA_FILES = [
    (
        "knowledge/droit_social/licenciement_economique",
        [
            str(p)
            for p in (
                REPO_ROOT
                / "knowledge"
                / "droit_social"
                / "licenciement_economique"
            ).glob("*.md")
        ]
        + [
            str(
                REPO_ROOT
                / "knowledge"
                / "droit_social"
                / "licenciement_economique"
                / "index.json"
            )
        ],
    ),
    ("", [str(REPO_ROOT / "config.dev.yaml")]),
]

OPTIONS = {
    # PyObjC gère son propre event loop, pas besoin de l'émulation argv.
    "argv_emulation": False,
    # Plist custom (metadata + usage strings TCC).
    "plist": str(REPO_ROOT / "packaging" / "Info.plist"),
    # Icône : à fournir plus tard (placeholder acceptable pour v1).
    # "iconfile": str(REPO_ROOT / "packaging" / "Lucie.icns"),
    # Packages Python à embarquer entiers.
    "packages": [
        "app",
        "lucie_v1_standalone",
    ],
    # Tree-shaking agressif — arbitrage tech lead du 2026-04-21.
    # Ces deps ne sont pas utilisées dans le chemin HUD v1 (dictée désactivée,
    # embeddings sentence-transformers pas encore branchés au HUD).
    # À réintroduire si/quand la dictée ou le RAG vectoriel seront activés.
    "excludes": [
        "torch",
        "torchvision",
        "torchaudio",
        "faster_whisper",
        "onnxruntime",
        "ctranslate2",
        "scipy",
        "sklearn",
        "sentence_transformers",
        "transformers",
        "tkinter",
        "test",
        "unittest",
        "pydoc_data",
        "IPython",
        "jupyter",
        "pytest",
        "mypy",
        "black",
        "ruff",
    ],
    # Strip des symboles debug pour réduire la taille.
    "strip": True,
    # semi_standalone=False → l'interpréteur Python 3.13 est embarqué.
    # Prérequis : lancer py2app depuis un python3.13 cible (pas un python
    # système 3.9).
    "semi_standalone": False,
    # Optimisation .pyc (équivalent python -O).
    "optimize": 1,
}

setup(
    name="Lucie",
    version="0.2.2",
    app=[APP_ENTRY],
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
