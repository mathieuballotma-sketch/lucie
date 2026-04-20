# Vendored: legi.py

- **Source** : https://github.com/Legilibre/legi.py
- **Commit SHA** : `64c2c49ad9a312714efac492627eae7e1eeb1cb0`
- **Licence** : [CC0 Public Domain Dedication](http://creativecommons.org/publicdomain/zero/1.0/)
- **Version vendorée dans Lucie** : `2026-04-20`

## Raison du vendoring

Projet inactif depuis novembre 2021 (`pushed_at: 2022-04-30`), officiellement Python
3.7-3.9. Lucie tourne sur Python 3.13. Vendorer permet de patcher localement sans
dépendre d'un upstream abandonné.

## Dépendances contournées

- **hunspell** : utilisé uniquement par `spelling.py` (requis par `anomalies.py` et
  optionnellement par `html.py`). Le module a un fallback gracieux
  (`fr_checker = Raiser(e)` → lève seulement à l'accès). Lucie n'active **jamais**
  la détection d'anomalies (`--anomalies=False`) et notre wrapper `parser.py`
  évite les chemins qui touchent `fr_checker.check()`.

## Usage dans Lucie

Seules les entrées `tar2sqlite.run()` / `db.connect_db()` sont appelées. Les autres
modules sont importés transitoires. Voir `lucie_v1_standalone/knowledge_legifrance/parser.py`
pour le wrapper officiel.

## Reproduire le vendoring

```bash
git clone --depth 1 https://github.com/Legilibre/legi.py /tmp/legi_src
cp -r /tmp/legi_src/legi/ lucie_v1_standalone/knowledge_legifrance/vendor/legi/
cd /tmp/legi_src && git rev-parse HEAD > .../vendor/legi/LEGI_PY_VERSION
```

Aucun patch in-place n'est appliqué à ce stade — le wrapper contourne les chemins
problématiques plutôt que modifier le code vendoré.
