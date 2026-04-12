# VISION.md — LUCIE : BIBLE STRATÉGIQUE ET TECHNIQUE

> Ce fichier est la référence unique pour toute décision stratégique ET technique.
> Quand tu hésites sur une direction : lis ce fichier. La réponse est ici.

---

## 1. CE QUE LUCIE PROUVE

Un assistant IA 100% local peut faire
ce qu'Apple promet depuis 3 ans
et n'a pas encore livré.

Un dev de 18 ans seul peut construire
ce qu'une équipe de 2000 ingénieurs
n'a pas réussi à livrer.

Chaque décision technique que tu prends
doit servir cette preuve.

---

## 2. PAYSAGE CONCURRENTIEL — OÙ ON EN EST

### 2.1 Les acteurs en place

| Projet | Stars | Forces | Limites |
|--------|-------|--------|---------|
| GPT4All | 70K | Simplicité, Windows+Mac+Linux | Agents basiques |
| PrivateGPT | 54K | RAG production-grade | Interface minimale |
| AnythingLLM | 54K | No-code builder, multi-plateforme | Pas natif macOS |
| Open Interpreter | 51K | Exécution code libre | Dangereux sans sandbox |
| Jan.ai | 41K | UI Apple-quality, modèles en 1 clic | Pas d'agents natifs |
| LM Studio | N/A | MLX = runtime optimal Apple Silicon | Fermé, pas extensible |
| Msty | N/A | Présenté par Apple, UI premium | Propriétaire |
| LocalAI | N/A | Compatible OpenAI API, Agenthub | Complexe à configurer |
| OpenClaw | N/A | 3000+ skills | Dépend du cloud partiellement |
| Fabric | N/A | Patterns crowdsourcés | CLI uniquement |

### 2.2 Ce que Lucie fait que personne d'autre ne fait

**Lucie = le seul assistant qui combine :**
- 28 agents spécialisés coordonnés (cerveau bio-inspiré)
- Contrôle natif macOS via AppleScript + PyObjC
- 100% offline, zéro API externe
- Architecture multi-agent réactive via EventBus

Aucun concurrent ne fait le contrôle natif macOS avec une architecture multi-agent locale.
C'est le moat.

### 2.3 Faiblesses honnêtes à corriger

**1. Latence/runtime**
LM Studio + MLX est probablement le runtime le plus rapide sur Apple Silicon.
Ollama est compétitif mais pas optimal.
→ Roadmap : évaluer migration vllm-mlx pour les modèles critiques.

**2. UI/UX insuffisante**
Msty a une UI "Apple-quality" présentée par Apple.
Jan.ai a une interface ChatGPT-like propre.
AnythingLLM a un panel élégant.
Lucie n'a qu'un HUD + CLI.
→ Minimum viable : menu bar macOS + historique conversations + status agents.

**3. Écosystème fermé**
OpenClaw = 3000+ skills. AnythingLLM = no-code builder. Fabric = patterns crowdsourcés.
Les 28 agents fixes de Lucie ne suffisent pas à long terme.
→ Nécessaire : plugin system extensible (YAML/JSON par agent).

**4. Onboarding difficile**
Jan.ai, LM Studio, GPT4All ont des docs exhaustives + vidéos. Installation 1 clic = standard.
Si Lucie demande >3 min + terminal → handicap fatal pour adoption.
→ Nécessaire avant lancement : `brew install lucie` ou curl one-liner.

**5. Communauté inexistante**
GPT4All part à 70K stars. Lucie part de zéro.
→ Strategy : Show HN + r/LocalLLaMA + build in public 30 jours.

**6. macOS-only (choix assumé)**
Tous les majeurs font Win+macOS+Linux.
Lucie est macOS-only — c'est un choix stratégique : profondeur > largeur.
Ce choix se justifie si le contrôle natif macOS est irréplicable.
Ne jamais sacrifier ce choix pour de la largeur superficielle.

---

## 3. AVANTAGES QU'APPLE NE PEUT PAS RÉPLIQUER

Quand tu prends une décision technique,
demande-toi si elle renforce ces avantages :

1. **Zéro donnée sortante** — rien ne quitte le Mac
2. **Modèles libres** — l'utilisateur choisit, change, fine-tune
3. **Prix libre** — pas lié à l'écosystème Apple, pas d'abonnement
4. **Secteurs interdits au cloud** — médecins, avocats, comptables, militaires
5. **Contrôle natif profond** — AppleScript + PyObjC, pas des raccourcis clavier simulés

Si une optimisation sacrifie l'un de ces points
→ IGNORÉE, peu importe le gain de performance.

---

## 4. MÉTRIQUES CIBLES — CE QUI EST MESURABLE

Ces chiffres définissent "impeccable".
En dessous = pas acceptable pour la démo.

| Action | Cible | Actuel |
|--------|-------|--------|
| Salutation "bonjour" | 0ms | 0ms ✅ |
| Ouvrir une app | < 0.5s | ~0.4s ✅ |
| Créer note/rappel | < 1s | ~0.5s ✅ |
| Traiter 5 mails | < 10s | ~17s ⚠️ |
| Safari 1 site | < 10s | ~15s ⚠️ |
| Safari 3 sites | < 20s | ~35s ⚠️ |
| Wake word → écoute | < 0.3s | ~0.2s ✅ |
| Transcription Whisper | < 1s | ~1s ✅ |
| Vision écran | < 4s | ? |

---

## 5. STANDARDS DE QUALITÉ — CE QU'ON VEUT vs CE QU'ON A

### 5.1 Réponses vocales

❌ Ce qu'on a :
"J'ai bien reçu votre demande d'ouvrir
l'application Safari. L'application a été
ouverte avec succès."

✅ Ce qu'on veut :
"Safari ouvert."

Règle : la réponse vocale doit être ≤ 2 secondes à l'oral.
Si c'est plus long, c'est trop long.

---

### 5.2 Gestion des erreurs

❌ Ce qu'on a :
```python
except Exception as e:
    pass  # 39 occurrences dans le projet
```

✅ Ce qu'on veut :
```python
except AppleScriptError as e:
    logger.error(f"❌ AppleScript échoué: {e}")
    return "Impossible d'exécuter cette action."
except TimeoutError:
    logger.warning("⏰ Timeout AppleScript")
    return "Action trop longue, réessaie."
```

Règle : chaque exception doit être loggée
et retourner un message français clair.
Jamais de stack trace à l'utilisateur.

---

### 5.3 Confiance LLM → fallback Safari

❌ Ce qu'on a :
LLM répond même quand il ne sait pas.
Résultat : réponses inventées ou vagues.

✅ Ce qu'on veut :
Si confidence < seuil → Safari cherche.
"Hey Lucie, cours du bitcoin ?"
→ LLM détecte qu'il ne peut pas savoir
→ Safari cherche en temps réel
→ Réponse factuelle en < 10s

---

### 5.4 Mémoire inter-sessions

❌ Ce qu'on a :
MemoryGraph repart à zéro chaque session.

✅ Ce qu'on veut :
Contextes récurrents persistés.
"Hey Lucie, le vendredi c'est deadline Marchand."
→ Vendredi suivant, Lucie le sait déjà.

---

## 6. ANTI-PATTERNS — CE QU'ON NE FAIT PAS

Ces patterns détruisent la démo.
Si tu les trouves dans le code, corrige-les.

**Anti-pattern 1 — Réponse bavarde**
```python
# ❌
return f"J'ai bien reçu votre demande et j'ai effectué
l'action demandée avec succès. L'opération s'est
déroulée correctement."

# ✅
return "✅ Safari ouvert."
```

**Anti-pattern 2 — Timeout absent**
```python
# ❌
subprocess.run(["osascript", script])

# ✅
subprocess.run(["osascript", script], timeout=8.0)
```

**Anti-pattern 3 — Ressource non fermée**
```python
# ❌
stream = sd.InputStream(...)
stream.start()
# ... si exception ici → stream jamais fermé

# ✅
with sd.InputStream(...) as stream:
    # stream toujours fermé même si exception
```

**Anti-pattern 4 — Traitement séquentiel inutile**
```python
# ❌ — 17s pour 5 mails
for mail in mails:
    result = await classify(mail)

# ✅ — ~8s pour 5 mails
results = await asyncio.gather(
    *[classify(mail) for mail in mails],
    return_exceptions=True
)
```

---

## 7. EXEMPLES DE PATTERNS CORRECTS

Ces patterns existent déjà dans le projet.
Utilise-les comme référence.

**Pattern AppleScript correct :**
Voir app/agents/smart_mail_agent.py
→ méthode _run_applescript()

**Pattern async correct :**
Voir app/agents/safari_research_workflow.py
→ méthode _step3_visit_sites()

**Pattern logging correct :**
Voir app/agents/smart_mail_agent.py
→ logs avec émojis + contexte français

---

## 8. PIPELINES PRIORITAIRES

### P1 — Brief du matin (démo principale)
Commande : "Hey Lucie, brief du matin"
Pipeline :
1. SmartMailAgent → urgents + deadlines
2. CalendarAgent → réunions du jour
3. SafariAgent → 1 recherche contextuelle
4. Synthèse vocale ≤ 30 secondes

Impact démo : maximal.
Un seul "Hey Lucie" remplace
10 minutes de vérification manuelle.

### P2 — Fallback Safari automatique
Déclencheur : confidence LLM < 0.6
sur une question factuelle.
Impact démo : élimine les hallucinations.

### P3 — Wake word "Hey Lucie"
10 minutes d'entraînement OpenWakeWord.
Impact démo : identité du produit.
"Hey Jarvis" fait penser à Iron Man.
"Hey Lucie" fait penser à un produit réel.

### P4 — Prépare ma réunion
Pipeline CalendarAgent + SmartMailAgent
+ SafariAgent + DocumentAgent.
Impact démo : cas d'usage professionnel concret.

---

## 9. FEATURES MANQUANTES — CLASSÉES PAR PRIORITÉ

### 🔴 CRITIQUES (avant lancement)

**1. Plugin/Skill System extensible**
Format YAML/JSON par agent : schema, description, triggers, Python.
Sans ça, Lucie est un produit fermé. Les 28 agents fixes ne suffisent pas.

**2. API REST locale compatible OpenAI sur localhost**
Toute l'écosystème d'outils (Open WebUI, SillyTavern, etc.) branchable en 1 ligne.
Différenciateur immédiat pour les power users.

**3. UI minimale**
Menu bar macOS + historique conversations + status agents en temps réel.
Minimum pour ne pas perdre les non-développeurs à la démo.

**4. Installation 1 commande**
`brew install lucie` ou curl one-liner.
Si l'installation prend >3 min ou demande un terminal : adoption morte.

### 🟡 IMPORTANTS (3 mois post-lancement)

**5. Voice local complet**
Whisper.cpp (input) + Piper TTS (output).
Actuellement partiel. Compléter le pipeline end-to-end.

**6. Multi-modal complet**
Vision + audio + texte + génération images (Stable Diffusion local).
Démo "analyse ce PDF" devient "analyse cette image".

**7. Automation workflows IFTTT-like local**
Triggers + conditions + actions en langage naturel.
"Quand je reçois un mail de X, résume-le et bloque 30 min dans mon agenda."

**8. Mémoire persistante structurée**
ChromaDB/Qdrant local + mémoire épisodique enrichie.
La mémoire est le différenciateur clé vs un simple chatbot.

### 🟢 NICE-TO-HAVE (6 mois+)

**9. Mode collaboratif local multi-utilisateur**
Réseau local, partage d'agents entre machines.

**10. Marketplace d'agents communautaires**
Upload/download d'agents custom. Fabric-like mais pour Lucie.

**11. Dashboard monitoring**
Agents actifs, latence par agent, mémoire utilisée, CPU, logs en direct.

**12. Intégration Shortcuts macOS → agents Lucie**
Trigger Lucie depuis n'importe quelle app via Shortcuts.

---

## 10. STRATÉGIE DE LANCEMENT

### 10.1 Séquence recommandée

1. **Semaine 0** : Show HN (mardi/mercredi 9-10h EST)
2. **Semaine 1** : r/LocalLLaMA post benchmark
3. **Semaine 1** : Thread Twitter + vidéo 45s
4. **Semaine 2** : Product Hunt
5. **Semaine 2-4** : Build in public (1 tweet/jour, 30 jours)
6. **Mois 2** : Ollama Discord #showcase, podcasteurs FR

### 10.2 Show HN

**Titre :** "Show HN: Lucie – 28 AI agents that control your Mac natively, 100% offline, zero cloud"

Ce qui fonctionne sur HN :
- Commencer par la démo, pas la technique
- L'architecture cerveau bio-inspiré = angle différenciant
- Repo GitHub + vidéo 90s dans le premier commentaire
- Répondre à chaque commentaire dans les 2 premières heures

### 10.3 r/LocalLLaMA

**Angle :** "I built a 28-agent AI assistant that runs 100% locally on macOS — here's what I learned about multi-agent orchestration with local models"

Ce que le sub veut :
- Benchmarks concrets : modèle, quantization, latence par agent, RAM utilisée
- Schémas d'architecture (EventBus, FrontalCortex)
- Ce qui n'a pas marché et pourquoi
- Code source accessible

### 10.4 Premier tweet @LucieLocal

**Format :** Thread viral avec vidéo 45s
**Hook :** "28 AI brains. Zero cloud. Zero API. Zero subscription."
**Triple négation** = mémorable et différenciant.

### 10.5 Vidéo démo 60-90s (4 actions enchaînées)

| Segment | Durée | Action |
|---------|-------|--------|
| Brief matin | 0-20s | Lit 3 mails, identifie l'urgent |
| Multi-app | 20-40s | Prépare la réponse + bloque le calendrier |
| Recherche web | 40-55s | Safari contextuel sans prompt manuel |
| Vision + action | 55-75s | Analyse PDF à l'écran, extrait les chiffres |

**Closer :** "28 agents. Zero cloud. Your Mac, supercharged."

Règles de la vidéo :
- Zéro clavier visible, zéro souris
- Pas de coupure de montage sur les actions
- Fond sonore minimal, voix de Lucie claire
- Sous-titres obligatoires (Twitter mute par défaut)

### 10.6 Acquisition des 10 premiers utilisateurs

| Canal | Action |
|-------|--------|
| r/LocalLLaMA | DM aux power users avec accès anticipé |
| Ollama Discord | Post dans #showcase |
| Twitter AI builders | Engager les threads sur local AI |
| Podcasteurs FR | Underscore_, NoLimitSecu — pitch vidéo |
| Discord Lucie | Ouvrir #bugs, #feature-requests, #show-your-setup |

**Build in public :** 1 tweet/jour pendant 30 jours.
Montrer les métriques réelles, les bugs, les décisions.
Rien ne construit la confiance comme la transparence brutale.

---

## 11. CRITÈRE FINAL

La démo de 60 secondes.

4 actions enchaînées.
Zéro clavier. Zéro souris. Zéro cloud.
Aucune hésitation. Aucun bug visible.

Si un ingénieur Apple regarde cette démo
et ne peut pas expliquer à son équipe
pourquoi Lucie existe et ce qu'elle prouve —
alors le travail n'est pas fini.
