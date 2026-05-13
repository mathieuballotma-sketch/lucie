# Modèle de menace — Beaume

*[Read in English](THREAT_MODEL.md)*

Document public. Décrit ce qui menace les utilisateurs de Beaume et
ce que l'architecture protège.

---

## Modèle d'utilisation

Beaume tourne sur le Mac d'un avocat. L'avocat tape une question de
droit social ou colle un extrait de dossier client. Beaume retourne
une réponse avec citations Légifrance vérifiées.

**Périmètre de confidentialité** : tout ce qui entre dans Beaume reste
sur la machine de l'avocat. Aucune donnée client ne sort.

---

## Surfaces d'attaque considérées

### Surface 1 — Exfiltration réseau

**Menace** : un attaquant ou un défaut de conception fait sortir une
donnée client de la machine.

**Mitigations** :
- Aucun appel HTTP sortant en runtime, hors `127.0.0.1:11434` (Ollama
  local). Vérifiable : `grep -rE "https?://" lucie_v1_standalone/ --include='*.py' | grep -v localhost | grep -v 127.0.0.1`.
- Modèle LLM (Gemma 4 e4b) téléchargé une fois via Ollama puis exécuté
  100 % localement. Pas d'API key, pas de compte utilisateur LLM.
- KB Légifrance générée localement à partir des archives DILA publiques.

### Surface 2 — Lecture des fichiers utilisateurs

**Menace** : Beaume lit un fichier utilisateur qu'elle ne devrait pas.

**Mitigations** :
- Le module de lecture dossier (Sprint 7, en cours) lit uniquement les
  fichiers explicitement glissés-déposés dans le HUD.
- Pas de scan automatique du Finder ou des dossiers Documents/.
- Sandbox macOS natif appliqué par la signature Developer ID prévue
  pour le build `.dmg`.

### Surface 3 — Audit trail

**Menace** : un avocat ne peut pas prouver après coup ce que Beaume
lui a dit (et avec quelles sources).

**Mitigations** :
- Chaque réponse expose explicitement les citations Légifrance utilisées
  + le `verifier_score`.
- Les conversations sont stockées localement dans
  `~/Library/Application Support/Beaume/` et peuvent être exportées au
  format PAF (preuve audit format).
- Cf bouton « Exporter audit PAF » dans le menubar HUD.

### Surface 4 — Mémoire adaptative

**Menace** : la mémoire utilisateur accumule des données sensibles
client et les redivulgue.

**Mitigations** :
- Sanitizer PII applique des règles de détection (numéros SS, IBAN,
  noms propres) avant écriture mémoire — voir
  [`lucie_v1_standalone/memory/sanitizer.py`](../lucie_v1_standalone/memory/sanitizer.py).
- La page « Ce que Beaume sait de vous » du HUD expose explicitement
  toute la mémoire et permet un reset complet en un clic.

---

## Modèle de menace côté code

### Le code est public, c'est intentionnel

Beaume est sous Business Source License 1.1. Le code peut être lu et
étudié. La copie commerciale en production n'est pas autorisée
pendant 4 ans.

Ce qui n'est **pas** dans le repo public :
- L'index Légifrance compacté (4,6 Go SQLite) — généré localement à
  partir des archives DILA publiques.
- Les prompts de tuning fin et les seuils détaillés calibrés
  empiriquement — réserve interne.
- Les rapports diagnostic complets (causes racines, métriques internes)
  — voir [`docs/sprints/SUMMARY.fr.md`](sprints/SUMMARY.fr.md) pour la doctrine.

### Si vous trouvez une vulnérabilité

**Ne pas ouvrir d'issue publique.** Contacter directement par email :

> mathieu.bellot via mathieu.ballotma@gmail.com (sujet : `[SECURITY]
> Beaume — votre titre court`)

Réponse sous 48h ouvrées. Si la vulnérabilité concerne une donnée
client réelle, joindre le contexte d'usage (modèle, version) mais
**aucun extrait de dossier client réel** — Beaume étant locale, vous
disposez vous-même de la reproduction.
