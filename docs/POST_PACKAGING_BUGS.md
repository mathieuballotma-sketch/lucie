# POST_PACKAGING_BUGS.md — Bugs Python notés pendant le sprint packaging

Le sprint Packaging 0.5.0 a pour règle non-négociable : **ne pas corriger les
bugs Python découverts incidemment**. Cette doc sert de carnet : tout bug
constaté ici sera fixé dans un sprint dédié, pas en feature creep.

**Format** :
```
## [YYYY-MM-DD] — fichier:ligne — Description courte
**Découvert pendant** : ...
**Symptôme** : ...
**Reproduction** : ...
**Sévérité** : low | medium | high | bloquant
**Sprint cible** : (à définir)
```

---

## (vide au 2026-05-17)

Aucun bug Python n'a été trouvé pendant la phase de packaging. Le bundle
build proprement avec les `packaging/*.sh` existants, la negative grep ne
remonte rien.

Si l'avocat pilote remonte un bug à l'usage de Beaume 0.5.0, l'inscrire ici
avant de le triager dans un sprint hotfix.
