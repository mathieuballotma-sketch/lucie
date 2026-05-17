# Beaume — Installation Checklist (Mac vierge)

Checklist manuelle pour valider l'installation de **Beaume 0.5.0** sur un Mac de
test propre, avant de la donner à un avocat pilote. À cocher dans l'ordre.
Toute case rouge = sprint hotfix avant distribution.

**Versions visées** : macOS 13+ (Ventura/Sonoma/Sequoia), Apple Silicon
(M1/M2/M3/M4), 16 GB RAM, 10 GB d'espace disque libre.

---

## A. Pré-requis Mac vierge

- [ ] **A.1** macOS ≥ 13.0 (`sw_vers -productVersion`)
- [ ] **A.2** Apple Silicon (`uname -m` retourne `arm64`)
- [ ] **A.3** Au moins 10 GB libre (`df -h /` → colonne `Avail`)
- [ ] **A.4** Ollama installé (`brew install ollama && ollama serve &`)
- [ ] **A.5** Modèle Gemma 4 e4b tiré (`ollama pull gemma:4b-e4b`)
- [ ] **A.6** Port 11434 libre (`lsof -i:11434` → seul `ollama` doit l'écouter)

## B. Téléchargement du DMG

- [ ] **B.1** Beaume-0.5.0.dmg téléchargé depuis source officielle (GitHub
      Releases ou lien direct de Mathieu)
- [ ] **B.2** Hash SHA-256 vérifié contre celui annoncé dans la release notes
      (`shasum -a 256 Beaume-0.5.0.dmg`)
- [ ] **B.3** Pas d'attribut quarantine bloquant après téléchargement
      (`xattr Beaume-0.5.0.dmg` — `com.apple.quarantine` présent mais Gatekeeper
      doit l'accepter si l'app est notarized)

## C. Montage + installation

- [ ] **C.1** Double-clic sur le DMG → fenêtre Finder s'ouvre avec `Beaume.app`
      + lien `/Applications`
- [ ] **C.2** Glisser `Beaume.app` dans `Applications`
- [ ] **C.3** **Aucun message** "logiciel non identifié, impossible à ouvrir"
      (si l'app est signée+notarized correctement)
- [ ] **C.4** Démonter le DMG via Finder (icône eject)

## D. Premier lancement

- [ ] **D.1** Double-clic sur `Beaume.app` dans `/Applications`
- [ ] **D.2** Dialog macOS "Beaume" demande accès microphone / accessibilité /
      AppleEvents → tout refuser pour ce test (Beaume doit dégrader proprement)
- [ ] **D.3** Warm-up Ollama : le HUD apparaît en moins de 90 secondes
      (premier lancement à froid, charge `gemma:4b-e4b` en RAM)
- [ ] **D.4** Fenêtre HUD visible, focus sur champ de saisie

## E. Test fonctionnel

- [ ] **E.1** Poser la question test :
      _"Je dois licencier 5 salariés pour motif économique, quelle est la
      procédure ?"_
- [ ] **E.2** Réponse en < 30 s (M4) ou < 60 s (M1)
- [ ] **E.3** Réponse contient au moins une citation `Art. L. 1233-XX` du Code
      du travail (pas de "je ne peux pas répondre")
- [ ] **E.4** Pas d'hallucination flagrante (sources cohérentes avec la KB)

## F. Vérif sécurité (invariant Beaume 100% local)

- [ ] **F.1** Ouvrir Activity Monitor → onglet Network → filtrer sur "Beaume"
- [ ] **F.2** Pendant la question test, **seules** des connexions vers
      `localhost:11434` (Ollama) doivent apparaître
- [ ] **F.3** Zéro octet sortant vers `*.openai.com`, `*.anthropic.com`,
      `*.sentry.io`, `*.posthog.com`, ou tout autre domaine externe
- [ ] **F.4** Aucun process tiers spawné (`ps -ef | grep -i beaume` → seul
      `Beaume` + ses workers Python)

## G. Logs / crashs

- [ ] **G.1** Pas de crash report dans `~/Library/Logs/DiagnosticReports/`
      (filtrer sur `Beaume*`)
- [ ] **G.2** Logs applicatifs (si dispo via menu Help → Show Logs) ne
      contiennent pas de stack trace
- [ ] **G.3** Quitter via menu Beaume → Quit → l'app se ferme proprement
      (pas de processus zombie : `ps -ef | grep -i beaume` retourne vide après
      30 s)

## H. Désinstallation (nettoyage avant remise à zéro)

- [ ] **H.1** `rm -rf /Applications/Beaume.app`
- [ ] **H.2** `rm -rf ~/Library/Application\ Support/Beaume`
- [ ] **H.3** `rm -rf ~/Library/Caches/com.mon-agence-ia.beaume`
- [ ] **H.4** `rm -rf ~/Library/Preferences/com.mon-agence-ia.beaume.plist`

---

## Verdict

Si **toutes les cases** sont vertes → Beaume 0.5.0 prêt pour distribution alpha
avocats (juin-juillet 2026).

Si **une case rouge en C/D/E/F** → bloquant, hotfix requis avant remise au pilote.
Si **une case rouge en B/G/H** → non-bloquant, log dans `docs/POST_PACKAGING_BUGS.md`.

Date du test : __________________________
Tested by    : __________________________
DMG hash     : __________________________
