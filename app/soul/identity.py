"""
Gestion de l'identité de l'agent (SOUL.md).
Définit la personnalité, les objectifs, les valeurs.
"""

from pathlib import Path
from typing import Dict, Any

class SoulIdentity:
    def __init__(self, soul_path: str = "~/AgentLucide/SOUL.md"):
        self.soul_path = Path(soul_path).expanduser()
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.soul_path.exists():
            # Créer un fichier par défaut
            default = """# Identité d'Agent Lucie

## Personnalité
- Amical, serviable, concis
- Respectueux de la vie privée
- Apprend des interactions

## Objectifs principaux
- Assister l'utilisateur dans ses tâches quotidiennes
- Maintenir la sécurité et l'intégrité du système
- S'adapter aux préférences de l'utilisateur

## Valeurs
- Transparence
- Autonomie de l'utilisateur
- Fiabilité
"""
            self.soul_path.write_text(default)
            return self._parse(default)
        return self._parse(self.soul_path.read_text())

    def _parse(self, content: str) -> Dict[str, Any]:
        # Parse simple par sections
        lines = content.split('\n')
        data = {}
        current_section = None
        current_list: list[str] = []
        for line in lines:
            line = line.strip()
            if line.startswith('## '):
                if current_section:
                    data[current_section] = current_list
                current_section = line[3:].strip()
                current_list = []
            elif line.startswith('- ') and current_section:
                current_list.append(line[2:].strip())
            elif line and not line.startswith('#') and current_section:
                current_list.append(line)
        if current_section:
            data[current_section] = current_list
        return data

    def get_personality(self) -> str:
        return "\n".join(self.data.get("Personnalité", []))

    def get_objectives(self) -> list[str]:
        return list(self.data.get("Objectifs principaux", []))

    def update(self, key: str, value: Any) -> None:
        # Pour mise à jour programmatique (ex: après apprentissage)
        # Réécrire le fichier entier (simplifié)
        self.data[key] = value if isinstance(value, list) else [value]
        self._save()

    def _save(self) -> None:
        with open(self.soul_path, 'w') as f:
            f.write("# Identité d'Agent Lucie\n\n")
            for section, items in self.data.items():
                f.write(f"## {section}\n")
                for item in items:
                    f.write(f"- {item}\n")
                f.write("\n")
