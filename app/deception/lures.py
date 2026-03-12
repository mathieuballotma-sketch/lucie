"""
Générateur de leurres - Crée des fichiers factices pour piéger les attaquants.
"""

import os
import uuid
import random
import string
from pathlib import Path
from typing import Optional
import aiofiles

from app.utils.logger import logger


class LureGenerator:
    """
    Générateur de leurres (fichiers, ports, etc.).
    """

    def __init__(self, config: dict, lures_dir: Path):
        self.config = config
        self.lures_dir = lures_dir

    async def create_file_lure(self, directory: str, name_hint: Optional[str] = None) -> str:
        """
        Crée un fichier leurre (ex: passwords.txt, config.json) avec un traceur.
        """
        # Déterminer le nom du fichier
        if name_hint:
            # Nettoyer le hint pour en faire un nom de fichier
            name = name_hint.replace(" ", "_").lower()
            if not name.endswith(('.txt', '.json', '.xlsx')):
                name += '.txt'
        else:
            # Noms de fichiers courants pour les leurres
            candidates = [
                "passwords.txt",
                "config.json",
                "bank_details.xlsx",
                "private_key.pem",
                "database.sql",
                "secret.docx",
            ]
            name = random.choice(candidates)

        # Chemin complet
        lure_path = os.path.join(directory, name)

        # Générer un identifiant unique pour ce leurre
        lure_id = uuid.uuid4().hex

        # Contenu du leurre avec traceur
        content = f"""# FICHIER LEURRE - AGENT LUCIDE
# ID: {lure_id}
# Ce fichier est un leurre. Toute tentative d'accès sera enregistrée.

---
DONNÉES SENSIBLES (SIMULÉES)
---
Utilisateur: admin
Mot de passe: {''.join(random.choices(string.ascii_letters + string.digits, k=12))}
Token: {uuid.uuid4().hex}
---
Ne pas diffuser.
"""
        # Écrire le fichier
        async with aiofiles.open(lure_path, 'w') as f:
            await f.write(content)

        logger.info(f"Leurre créé: {lure_path} (ID: {lure_id})")
        return lure_path

    async def create_generic_lure(self, directory: str) -> str:
        """
        Crée un leurre générique (fichier texte simple).
        """
        name = f"lure_{uuid.uuid4().hex[:8]}.txt"
        lure_path = os.path.join(directory, name)

        content = f"""Ceci est un leurre généré par Agent Lucide.
ID: {uuid.uuid4().hex}
Timestamp: {time.time()}
"""
        async with aiofiles.open(lure_path, 'w') as f:
            await f.write(content)

        return lure_path