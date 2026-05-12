# Security

## Modèle de menace en 3 lignes

Beaume tourne sur le Mac d'un avocat. Les données d'un dossier client
n'en sortent jamais — aucun appel HTTP sortant en runtime hors
`127.0.0.1:11434` (Ollama local). Le détail des surfaces d'attaque
considérées est dans [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

## Signaler une vulnérabilité

**Ne pas ouvrir d'issue publique.** Contacter directement :

> Mathieu Bellot — mathieu.ballotma@gmail.com
> Sujet : `[SECURITY] Beaume — <titre court>`

Réponse sous 48 h ouvrées. Si la vulnérabilité concerne une donnée
client réelle, joindre le contexte d'usage (modèle, version) mais
**aucun extrait de dossier client réel** — Beaume étant locale, vous
disposez vous-même de la reproduction sur votre propre machine.

## Périmètre de la divulgation responsable

| Catégorie | Action |
|-----------|--------|
| Vulnérabilité critique (exfiltration de données) | divulgation après fix, crédit dans `CHANGELOG.md` |
| Vulnérabilité élevée (élévation de privilèges, lecture fichiers hors sandbox) | idem, sous 30 jours |
| Vulnérabilité modérée (DoS local) | sous 90 jours |
| Vulnérabilité faible (info disclosure non sensible) | fix au prochain sprint, mention dans `CHANGELOG.md` |

## Ce qui n'est pas une vulnérabilité

- Une hallucination LLM passée à travers le Vérificateur : c'est un
  bug de fiabilité, pas une vulnérabilité de sécurité. Ouvrir une
  issue GitHub normale avec le prompt qui déclenche.
- Un fichier dossier client lu par Beaume après que l'utilisateur l'a
  lui-même glissé-déposé : c'est le comportement attendu.
- Le code public lu et étudié : c'est intentionnel (BSL 1.1). La
  copie commerciale n'est pas autorisée pendant 4 ans, c'est une
  question juridique, pas de sécurité.

## Versions supportées

| Version | Support sécurité |
|---------|------------------|
| `main` (HEAD) | oui |
| Releases tagged (à venir, post-pilote) | oui pour la dernière mineure |
| Pre-Sprint 6 (avant 2026-04-23) | non, pre-pivot |

## Référence

- [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) — modèle de menace
  détaillé par surface d'attaque
- [`LICENSE`](LICENSE) — Business Source License 1.1
- [`PRINCIPLES.md`](PRINCIPLES.md) — principe 1 (100 % local) et
  principe 4 (transparence radicale)
