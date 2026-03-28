"""
Neutraliseur de menaces - Met en quarantaine et crée des leurres.
"""

import shutil
import uuid
import time  # <-- AJOUT
import json
from pathlib import Path
from typing import Dict, Any, Optional
import aiofiles

from app.utils.logger import logger


class ThreatNeutralizer:
    """
    Gère la mise en quarantaine des fichiers malveillants et la création de leurres.
    """

    def __init__(self, config: Dict[str, Any], quarantine_dir: Path, lures_dir: Path) -> None:
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
        Crée un fichier leurre inoffensif dans le répertoire des leurres.
        """
        src = Path(original_path)
        # Générer un nom unique pour le leurre
        unique_id = uuid.uuid4().hex[:8]
        lure_name = f"{unique_id}_{src.name}"
        lure_path = self.lures_dir / lure_name

        # Contenu du leurre (par exemple, un message)
        content = f"""Ce fichier est un leurre créé par Agent Lucide.
Il a remplacé un fichier potentiellement malveillant: {src.name}
Type de menace: {threat_info.get('type', 'inconnu')}
Date de création: {time.ctime()}

-- Agent Lucide, système immunitaire numérique
"""

        # Écrire le leurre
        async with aiofiles.open(lure_path, 'w') as f:
            await f.write(content)

        # Enregistrer les métadonnées du leurre
        meta_file = lure_path.with_suffix('.meta.json')
        meta = {
            "original_path": str(src),
            "threat": threat_info,
            "created": time.time(),
            "type": "lure"
        }
        async with aiofiles.open(meta_file, 'w') as f:
            await f.write(json.dumps(meta, indent=2))

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
