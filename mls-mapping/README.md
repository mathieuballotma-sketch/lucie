# MLS — Mapping psychédélique

Animation plein écran pour projection / mapping vidéo :
le logo **MLS (Monte Le Son)** clignote, change de couleur en boucle,
entouré de points psychédéliques qui tournent et scintillent.

## Utilisation

1. Enregistre ton logo sous le nom **`mls-logo.png`** dans ce dossier
   (à côté de `mls-mapping.html`).
2. Ouvre `mls-mapping.html` dans un navigateur (Chrome / Firefox).
3. Appuie sur **F** pour passer en plein écran, puis branche le vidéoprojecteur.

> Astuce : un PNG à fond transparent rend l'effet de glow encore plus net.

## Commandes clavier

| Touche | Action |
|--------|--------|
| `F`    | Plein écran (on/off) |
| `+` / `-` | Accélérer / ralentir l'animation |
| `Espace` | Pause / reprise |

## Réglages

Tout est dans le `<style>` du fichier HTML, en haut (`:root`) :

- `--logo-size` : taille du logo (`46vmin` par défaut)
- `--speed` : vitesse globale

Dans le `<script>`, la constante `N` (≈140) contrôle le nombre de points.

100 % autonome, aucune dépendance, aucune connexion internet requise.
