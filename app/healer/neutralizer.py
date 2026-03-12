"""
Neutraliseur de menaces - Met en quarantaine et crée des leurres.
"""

import os
import shutil
import uuid
from pathlib import Path
from typing import Dict, Any, Optional
import aiofiles

from app.utils.logger import logger


class ThreatNeutralizer:
    """
    Gère la mise en quarantaine des fichiers malveillants et la création de leurres.
    """

    def __init__(self, config: dict, quarantine_dir: Path, lures_dir: Path):
        self.config = config
        self.quarantine_dir = quarantine_dir
        self.lures_dir = lures_dir

    async def quarantine(self, filepath: str, threat_info: Dict[str, Any]) -> Path:
        """
        Déplace un fichier vers le répertoire de quarantaine.
        """
        src = Path(filepath)
        if not src.exists():
            raise FileNotFoundError(f"Fichier introuvable: {filepath}")

        # Générer un nom unique pour éviter les collisions
        unique_id = uuid.uuid4().hex[:8]
        dest_name = f"{unique_id}_{src.name}"
        dest = self.quarantine_dir / dest_name

        # Déplacer le fichier
        shutil.move(str(src), str(dest))
        logger.info(f"Fichier mis en quarantaine: {src} -> {dest}")

        # Enregistrer les métadonnées de la menace
        meta_file = dest.with_suffix('.meta.json')
        meta = {
            "original_path": str(src),
            "threat": threat_info,
            "timestamp": time.time(),
        }
        async with aiofiles.open(meta_file, 'w') as f:
            await f.write(json.dumps(meta, indent=2))

        return dest

    async def create_lure(self, original_path: str, threat_info: Dict[str, Any]) -> Path:
        """
        Crée un fichier leurre inoffensif à l'emplacement d'origine.
        """
        src = Path(original_path)
        lure_path = src

        # Contenu du leurre (par exemple, un message)
        content = f"""Ce fichier a été neutralisé par Agent Lucide.
Il s'agissait potentiellement d'une menace de type: {threat_info.get('type', 'inconnu')}.
Si vous avez besoin du fichier original, veuillez consulter la quarantaine.

-- Agent Lucide, système immunitaire numérique
"""

        # Écrire le leurre
        async with aiofiles.open(lure_path, 'w') as f:
            await f.write(content)

        logger.info(f"Leurre créé: {lure_path}")
        return lure_path

    async def restore(self, quarantine_path: Path, original_path: Optional[Path] = None) -> Path:
        """
        Restaure un fichier depuis la quarantaine.
        """
        if not quarantine_path.exists():
            raise FileNotFoundError(f"Fichier en quarantaine introuvable: {quarantine_path}")

        # Lire les métadonnées pour connaître le chemin d'origine
        meta_file = quarantine_path.with_suffix('.meta.json')
        if meta_file.exists():
            async with aiofiles.open(meta_file, 'r') as f:
                meta = json.loads(await f.read())
            original = original_path or Path(meta.get("original_path", quarantine_path.name))
        else:
            original = original_path or Path.home() / quarantine_path.name

        # Restaurer
        shutil.move(str(quarantine_path), str(original))
        logger.info(f"Fichier restauré: {quarantine_path} -> {original}")

        # Supprimer le fichier de métadonnées
        if meta_file.exists():
            meta_file.unlink()

        return original