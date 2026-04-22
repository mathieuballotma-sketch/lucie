# Icônes app macOS — Lucie

Logo A validé le 2026-04-21 (serif éditorial EB Garamond, palette crème +
bleu-nuit #1a2847, wordmark + monogramme « L »).

## Contenu

```
icon/
├── icon_16x16.png     (menu bar)
├── icon_32x32.png     (favicon, menu bar @2x)
├── icon_64x64.png     (intermédiaire)
├── icon_128x128.png   (Finder moyen)
├── icon_256x256.png   (Finder grand)
├── icon_512x512.png   (Finder très grand)
└── icon_1024x1024.png (App Store, Retina @2x)

Lucie.iconset/  ← structure iconutil (voisin de ce dossier)
Lucie.icns       ← icône compilée embarquée par py2app
```

## Régénérer le .icns

`Lucie.icns` a été généré depuis `Proposition_A/` par Pillow (sandbox Linux).
Pour produire une `.icns` native Apple (plus propre pour la signature), sur
un Mac :

```bash
cd packaging
iconutil -c icns Lucie.iconset -o Lucie.icns
```

## Source

Les PNG sources viennent de
`~/Documents/Lucie/01_Produit/Identite_Visuelle/Proposition_A/app_icon_*.png`.
Si le logo évolue, regénérer ces PNG et relancer le script de duplication.
