"""
SEC-QW-01 : Vérification d'intégrité des modèles Ollama.

Au démarrage, calcule le SHA-256 des fichiers de modèles téléchargés
et compare avec les hash de référence stockés dans config/model_hashes.json.
Alerte (sans bloquer) si un modèle a été modifié ou corrompu.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Chemin par défaut du répertoire de stockage Ollama sur macOS/Linux
_OLLAMA_DEFAULT_DIRS = [
    Path.home() / ".ollama" / "models",
    Path("/usr/share/ollama/models"),
    Path("/var/lib/ollama/models"),
]

_DEFAULT_HASHES_FILE = Path(__file__).parent / "model_hashes.json"


class IntegrityError(Exception):
    """Levée quand un modèle échoue à la vérification d'intégrité."""


class ModelIntegrityChecker:
    """
    Vérifie l'intégrité SHA-256 des fichiers de modèles Ollama.

    Utilisation typique au démarrage ::

        checker = ModelIntegrityChecker()
        results = checker.verify_all()
        if results["tampered"] or results["missing_from_disk"]:
            logger.warning("Problème d'intégrité détecté — voir les logs.")
    """

    def __init__(
        self,
        hashes_file: Optional[Path] = None,
        ollama_dir: Optional[Path] = None,
    ) -> None:
        self.hashes_file = Path(hashes_file) if hashes_file else _DEFAULT_HASHES_FILE
        self.ollama_dir = Path(ollama_dir) if ollama_dir else self._detect_ollama_dir()
        self._known_hashes: dict[str, str] = {}
        self._load_hashes()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _detect_ollama_dir(self) -> Path:
        """Retourne le premier répertoire Ollama existant, ou le chemin par défaut."""
        for candidate in _OLLAMA_DEFAULT_DIRS:
            if candidate.exists():
                return candidate
        return _OLLAMA_DEFAULT_DIRS[0]

    def _load_hashes(self) -> None:
        """Charge le fichier de hashes de référence."""
        if not self.hashes_file.exists():
            logger.debug("Fichier de hashes absent : %s (sera créé à la première exécution)", self.hashes_file)
            return
        try:
            with open(self.hashes_file, encoding="utf-8") as fh:
                data = json.load(fh)
            self._known_hashes = data.get("models", {})
            logger.debug("%d hash(es) de référence chargé(s)", len(self._known_hashes))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Impossible de charger le fichier de hashes : %s", exc)

    # ------------------------------------------------------------------
    # Calcul de hash
    # ------------------------------------------------------------------

    @staticmethod
    def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
        """Calcule le SHA-256 d'un fichier par blocs de 1 Mo."""
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            while chunk := fh.read(chunk_size):
                h.update(chunk)
        return h.hexdigest()

    # ------------------------------------------------------------------
    # Vérification
    # ------------------------------------------------------------------

    def verify_model(self, model_name: str) -> dict:
        """
        Vérifie l'intégrité d'un modèle spécifique.

        Retourne un dict avec les clés :
        - ``model``     : nom du modèle
        - ``status``    : "ok" | "tampered" | "not_registered" | "missing_from_disk"
        - ``expected``  : hash attendu (peut être None)
        - ``actual``    : hash calculé (peut être None si fichier introuvable)
        - ``path``      : chemin du fichier (peut être None)
        """
        result: dict = {
            "model": model_name,
            "status": "not_registered",
            "expected": None,
            "actual": None,
            "path": None,
        }

        # Chercher le fichier de modèle (extension .gguf ou répertoire manifest Ollama)
        model_path = self._find_model_file(model_name)
        if model_path is None:
            result["status"] = "missing_from_disk"
            logger.warning("[IntégrityChecker] Modèle introuvable sur le disque : %s", model_name)
            return result

        result["path"] = str(model_path)
        actual_hash = self.sha256_file(model_path)
        result["actual"] = actual_hash

        expected_hash = self._known_hashes.get(model_name)
        result["expected"] = expected_hash

        if expected_hash is None:
            result["status"] = "not_registered"
            logger.info("[IntégrityChecker] %s non enregistré — hash actuel : %s", model_name, actual_hash)
        elif actual_hash == expected_hash:
            result["status"] = "ok"
            logger.debug("[IntégrityChecker] %s OK", model_name)
        else:
            result["status"] = "tampered"
            logger.error(
                "[IntégrityChecker] ALERTE : %s modifié ! attendu=%s actuel=%s",
                model_name, expected_hash, actual_hash,
            )

        return result

    def verify_all(self) -> dict:
        """
        Vérifie tous les modèles enregistrés dans le fichier de référence.

        Retourne un dict de synthèse ::

            {
                "ok": [...],
                "tampered": [...],
                "missing_from_disk": [...],
                "not_registered": [...],
                "details": {model_name: result_dict, ...},
            }
        """
        summary: dict = {
            "ok": [],
            "tampered": [],
            "missing_from_disk": [],
            "not_registered": [],
            "details": {},
        }

        models_to_check = list(self._known_hashes.keys())
        if not models_to_check:
            logger.info("[IntégrityChecker] Aucun modèle enregistré à vérifier.")
            return summary

        for model_name in models_to_check:
            res = self.verify_model(model_name)
            status = res["status"]
            summary[status].append(model_name)  # type: ignore[index]
            summary["details"][model_name] = res

        if summary["tampered"]:
            logger.error("[IntégrityChecker] %d modèle(s) compromis : %s", len(summary["tampered"]), summary["tampered"])
        if summary["missing_from_disk"]:
            logger.warning("[IntégrityChecker] %d modèle(s) absent(s) du disque : %s", len(summary["missing_from_disk"]), summary["missing_from_disk"])

        return summary

    # ------------------------------------------------------------------
    # Enregistrement d'un nouveau hash
    # ------------------------------------------------------------------

    def register_model(self, model_name: str, model_path: Optional[Path] = None) -> str:
        """
        Calcule et enregistre le hash du modèle dans le fichier de référence.

        Retourne le hash calculé.
        """
        path = Path(model_path) if model_path else self._find_model_file(model_name)
        if path is None or not path.exists():
            raise FileNotFoundError(f"Modèle introuvable : {model_name}")

        hash_value = self.sha256_file(path)
        self._known_hashes[model_name] = hash_value
        self._save_hashes()
        logger.info("[IntégrityChecker] Hash enregistré pour %s : %s", model_name, hash_value)
        return hash_value

    def _save_hashes(self) -> None:
        self.hashes_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"models": self._known_hashes}
        with open(self.hashes_file, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Localisation des fichiers modèles
    # ------------------------------------------------------------------

    def _find_model_file(self, model_name: str) -> Optional[Path]:
        """
        Cherche le fichier binaire d'un modèle Ollama.

        Ollama stocke ses blobs dans ``~/.ollama/models/blobs/`` et des
        manifests dans ``~/.ollama/models/manifests/``.  Cette méthode
        tente de localiser un fichier .gguf ou blob associé au modèle.
        """
        # Normaliser le nom (ex: "qwen2.5:7b" → "qwen2.5_7b")
        safe_name = model_name.replace(":", "_").replace("/", "_")

        # 1. Chercher un .gguf portant le nom du modèle
        for search_dir in [self.ollama_dir, self.ollama_dir.parent]:
            if not search_dir.exists():
                continue
            for candidate in search_dir.rglob(f"*{safe_name}*.gguf"):
                return candidate
            for candidate in search_dir.rglob(f"*{safe_name}*"):
                if candidate.is_file() and candidate.stat().st_size > 1_000_000:
                    return candidate

        # 2. Parcourir les manifests Ollama pour trouver le sha256 du blob
        manifest_root = self.ollama_dir / "manifests" / "registry.ollama.ai" / "library"
        if manifest_root.exists():
            name_part, _, tag = model_name.partition(":")
            tag = tag or "latest"
            manifest_path = manifest_root / name_part / tag
            if manifest_path.exists():
                return self._blob_from_manifest(manifest_path)

        return None

    def _blob_from_manifest(self, manifest_path: Path) -> Optional[Path]:
        """Extrait le chemin du blob principal depuis un manifest Ollama."""
        try:
            with open(manifest_path, encoding="utf-8") as fh:
                manifest = json.load(fh)
            layers = manifest.get("layers", [])
            for layer in layers:
                if "model" in layer.get("mediaType", ""):
                    digest: str = layer["digest"]  # ex: "sha256:abc123..."
                    algo, _, hex_val = digest.partition(":")
                    blob_path = self.ollama_dir / "blobs" / f"{algo}-{hex_val}"
                    if blob_path.exists():
                        return blob_path
        except (json.JSONDecodeError, KeyError, OSError):
            pass
        return None
