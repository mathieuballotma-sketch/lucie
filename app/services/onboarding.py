"""
Service d'onboarding pour Agent Lucide.
Gère le premier lancement : demande le prénom, crée un modèle personnalisé,
sauvegarde le profil utilisateur.
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from ..utils.logger import logger


PROFILE_PATH = Path("./data/user_profile.json")


def load_profile() -> Dict[str, Any]:
    """Charge le profil utilisateur depuis le fichier JSON."""
    if PROFILE_PATH.exists():
        try:
            data: Dict[str, Any] = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            return data
        except Exception as e:
            logger.error(f"Erreur chargement profil: {e}")
    return {}


def save_profile(profile: Dict[str, Any]) -> None:
    """Sauvegarde le profil utilisateur."""
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"✅ Profil sauvegardé: {PROFILE_PATH}")


def is_onboarded() -> bool:
    """Vérifie si l'utilisateur a déjà été onboardé."""
    profile = load_profile()
    return bool(profile.get("name"))


def get_user_name() -> Optional[str]:
    """Retourne le prénom de l'utilisateur, ou None si pas encore onboardé."""
    profile = load_profile()
    return profile.get("name")


def create_personal_model(name: str, base_model: str = "qwen2.5:7b") -> bool:
    """
    Crée un modèle Ollama personnalisé nommé {prenom}-ia:latest.

    Args:
        name: Prénom de l'utilisateur.
        base_model: Modèle de base à personnaliser.

    Returns:
        True si le modèle a été créé avec succès.
    """
    model_name = f"{name.lower()}-ia:latest"
    logger.info(f"🔧 Création du modèle personnalisé {model_name}...")

    modelfile_content = f'''FROM {base_model}

SYSTEM """Tu es l'assistant personnel de {name}. Tu le connais bien.
Tu réponds toujours en français, de manière amicale et directe.
Tu appelles l'utilisateur par son prénom : {name}.
Tu es Agent Lucide, une IA locale qui tourne sur la machine de {name}.
Tu es loyal, honnête et utile. Tu protèges la vie privée de {name}.
Quand {name} te pose une question personnelle, tu utilises tes souvenirs
de vos conversations passées pour contextualiser ta réponse."""

PARAMETER temperature 0.7
PARAMETER num_ctx 4096
'''

    modelfile_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".modelfile", delete=False
        ) as f:
            f.write(modelfile_content)
            modelfile_path = f.name

        result = subprocess.run(
            ["ollama", "create", model_name, "-f", modelfile_path],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            logger.info(f"✅ Modèle {model_name} créé avec succès")
            return True
        else:
            logger.error(f"Erreur création modèle: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Erreur création modèle personnalisé: {e}")
        return False
    finally:
        if modelfile_path:
            Path(modelfile_path).unlink(missing_ok=True)


def run_onboarding(name: str) -> Dict[str, Any]:
    """
    Exécute l'onboarding complet pour un nouvel utilisateur.

    Args:
        name: Prénom de l'utilisateur.

    Returns:
        Le profil utilisateur créé.
    """
    profile = load_profile()
    profile["name"] = name
    profile["model"] = f"{name.lower()}-ia:latest"
    profile["onboarded"] = True

    # Créer le modèle personnalisé
    model_created = create_personal_model(name)
    profile["model_created"] = model_created

    save_profile(profile)

    logger.info(f"🎉 Onboarding terminé pour {name}")
    return profile
