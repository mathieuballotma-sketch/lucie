# MLS — Mapping psychédélique réactif au son

Animation plein écran pour projection / mapping vidéo :
le logo **MLS (Monte Le Son)** clignote, change de couleur en boucle,
entouré de points psychédéliques qui tournent et scintillent.
L'ensemble **réagit à la musique** via le micro, avec **texte défilant**
et plusieurs **palettes** de couleurs.

## Utilisation

1. Enregistre ton logo sous le nom **`mls-logo.png`** dans ce dossier
   (à côté de `mls-mapping.html`).
2. Ouvre `mls-mapping.html` dans un navigateur (Chrome / Firefox).
3. Appuie sur **F** (plein écran), puis **M** pour activer le micro
   (autorise l'accès quand le navigateur le demande).
4. Branche le vidéoprojecteur et monte le son 🔊

> Astuce : un PNG à fond transparent rend l'effet de glow encore plus net.

## Commandes clavier

| Touche | Action |
|--------|--------|
| `F`        | Plein écran (on/off) |
| `M`        | Micro on/off — l'animation pulse sur les basses |
| `C`        | Changer de palette (Psyché, Néon MLS, Feu, Océan, Acide) |
| `+` / `-`  | Accélérer / ralentir |
| `↑` / `↓`  | Plus / moins de points |
| `T`        | Afficher / masquer le texte défilant |
| `Espace`   | Pause / reprise |

## Réactivité au son

Une fois le micro activé (**M**), l'énergie des basses (kick) :

- agrandit le logo à chaque temps fort,
- accélère et dilate les points psychédéliques,
- intensifie le halo de fond.

Le micro capte le son ambiant (enceintes) — idéal en soirée. Aucun son
n'est enregistré ni envoyé : tout reste dans le navigateur.

## Personnalisation rapide

Dans le `<style>` (haut du fichier, `:root`) :
- `--logo-size` : taille du logo
- `--speed` : vitesse globale

Dans le `<script>` :
- `N` : nombre de points (modifiable aussi en direct avec ↑/↓)
- `PALETTES` : ajoute/modifie tes propres jeux de couleurs (teintes HSL)
- Le texte défilant se change dans la balise `<span class="track">`.

100 % autonome, aucune dépendance, aucune connexion internet requise.
