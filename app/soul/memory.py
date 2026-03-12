"""
Mémoire persistante de l'agent (MEMORY.md).
Stocke les souvenirs importants, les préférences, les faits appris.
"""

from pathlib import Path
from typing import List, Dict, Any
import json
import time

class SoulMemory:
    def __init__(self, memory_path: str = "~/AgentLucide/MEMORY.md"):
        self.memory_path = Path(memory_path).expanduser()
        self.entries = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        if not self.memory_path.exists():
            return []
        content = self.memory_path.read_text()
        # Format : chaque entrée commence par ## [timestamp] Titre
        entries = []
        current = {}
        lines = content.split('\n')
        for line in lines:
            if line.startswith('## '):
                if current:
                    entries.append(current)
                # extraire timestamp et titre
                header = line[3:].strip()
                if ']' in header:
                    ts, title = header.split(']', 1)
                    ts = ts.strip('[')
                    title = title.strip()
                else:
                    ts = str(time.time())
                    title = header
                current = {'timestamp': float(ts) if ts.replace('.','').isdigit() else time.time(),
                           'title': title, 'content': ''}
            elif current:
                current['content'] += line + '\n'
        if current:
            entries.append(current)
        return entries

    def add(self, title: str, content: str):
        entry = {
            'timestamp': time.time(),
            'title': title,
            'content': content
        }
        self.entries.append(entry)
        self._save()
        # Optionnel : limiter la taille
        if len(self.entries) > 100:
            self.entries = self.entries[-100:]
            self._save()

    def search(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        # Recherche simple par mots-clés
        query_lower = query.lower()
        results = []
        for e in reversed(self.entries):
            if query_lower in e['title'].lower() or query_lower in e['content'].lower():
                results.append(e)
                if len(results) >= max_results:
                    break
        return results

    def get_recent(self, n: int = 5) -> List[Dict[str, Any]]:
        return self.entries[-n:]

    def _save(self):
        with open(self.memory_path, 'w') as f:
            for e in self.entries:
                f.write(f"## [{e['timestamp']}] {e['title']}\n")
                f.write(e['content'].strip() + "\n\n")