# CRYPTOMIND — SPÉCIFICATION COMPLÈTE
**Projet : Agent crypto personnel 100% local**
**Dernière mise à jour : 2026-04-01**
**Source : Training DeepSeek Sessions 1-3**

---

## VISION
Agent crypto personnel pour DCA automatique + Grid Trading hybride. 100% local (DeepSeek-R1 via Ollama), seules les API calls vers Binance pour les ordres. Budget initial : 50-200€/mois.

---

## SESSION 1 — STRATÉGIES, RISK MANAGEMENT, ARCHITECTURE

### Stratégies validées (backtests 3+ ans)

| Stratégie | CAGR | Max Drawdown | Adapté petit capital |
|---|---|---|---|
| DCA pur Bitcoin | ~28% | -77% | ✅ Oui |
| DCA + EMA200 filtre | ~31% | -65% | ✅ Oui |
| Grid Trading (BTC/USDT) | 8-12% annualisé (latéral) | Variable | ✅ Oui |
| DCA + Grid combiné | ~19% | -28% | ✅ Optimal |

### Risk Management — Règles en fer

| Règle | Valeur |
|---|---|
| Max par position | 1-2% du portfolio |
| Daily loss limit | 5% |
| Max drawdown (MDD) | -20% → STOP tout |
| Stop-loss | ATR-based dynamique |
| Corrélation risk | Max 2 positions corrélées |

### Architecture validée
- **Event-driven** : WebSocket pour prix temps réel + REST pour ordres
- **Circuit Breaker** : Backoff exponentiel sur erreurs API
- **Queue system** : File d'attente pour ordres (FIFO, pas de race condition)

### Sécurité des fonds
- API keys : trade-only (JAMAIS withdrawal)
- IP whitelist sur Binance
- Hot wallet = montant minimum pour trading
- Cold storage = gros du portfolio (hors bot)

---

## SESSION 2 — INDICATEURS, BACKTESTING, LLM

### Indicateurs techniques validés

**À UTILISER :**

| Indicateur | Paramètres | Usage |
|---|---|---|
| RSI(7) double filtre | <20 sur 15m ET 4h | Entrée DCA aggressive |
| EMA 200 | - | Filtre de tendance (bull/bear) |
| VWAP 24h | - | Zone de valeur (accumulation) |
| ATR(14) | - | Espacement dynamique des grilles |

**À IGNORER :** MACD (trop lent), Bollinger Bands (overfitting), Ichimoku (trop complexe)

### Backtesting — Méthodologie

**Walk-Forward Analysis :**
```
Données totales : 4 ans (2022-2026)
├── In-sample (optimisation) : 2022-2023 (2 ans)
├── Out-of-sample (validation) : 2024 (1 an)
└── Test final : 2025-2026 (1 an)
```

**Métriques requises :**
- Sharpe ratio > 1.0
- Max Drawdown < 50%
- Profit Factor > 1.2
- Min 200 trades pour significativité statistique

**Frais à modéliser :**
- Binance spot : 0.1% taker (0.075% avec BNB)
- Slippage : BTC 0.05%, ETH 0.07%, altcoins 0.10-0.50%
- Latence : 500ms-2s (non critique pour DCA/Grid)

**Frameworks :** Backtrader (rigueur) → VectorBT (performance grid)

### Fear & Greed Index — VALIDÉ

Backtest 2018-2023 (5+ ans) :
| Stratégie | ROI |
|---|---|
| DCA pur ($100/semaine) | 124.8% |
| DCA modulé (Fear/Greed) | 140.1% |
| DCA modulé + vente 5% Extreme Greed | **184.2%** |

**Seuils d'action :**
| Score | Sentiment | Action DCA | Action Grid |
|---|---|---|---|
| < 25 | Extreme Fear | +50% montant | Élargir grille |
| 25-44 | Fear | +25% montant | Normal |
| 45-55 | Neutral | Normal | Normal |
| 56-75 | Greed | -25% montant | Réduire exposition |
| > 75 | Extreme Greed | -50% + vente 5% | Suspendre |

**API :** `https://api.alternative.me/fng/?limit=1` (gratuit, sans clé)

### On-Chain Data

| Métrique | Signal | Source |
|---|---|---|
| MVRV < 1.0 | Zone accumulation (bottom historique) | CoinGecko (gratuit) |
| MVRV > 3.7 | Zone de vente (top cyclique) | CoinGecko (gratuit) |
| NVT | Moyenne pertinence | Glassnode (payant) |
| Exchange inflows | Bonne pertinence | CryptoQuant (payant) |

**Recommandation petit capital :** MVRV + Fear & Greed seulement (gratuits).

### Intégration LLM (DeepSeek-R1 8B via Ollama)

**RÈGLE D'OR : Le LLM ne prend JAMAIS de décision de trading automatique.**

**Usages validés :**
- ✅ Analyse sentiment news crypto
- ✅ Résumé conditions marché (rapport quotidien)
- ✅ Aide configuration paramètres
- ✅ Analyse post-mortem des trades (reflection agent)

**Limites réelles :**
| Limite | Impact | Mitigation |
|---|---|---|
| Hallucinations | Peut inventer des données | Toujours vérifier avec données réelles |
| Pas de raisonnement numérique précis | Mauvais pour position sizing | Calculs dans le code Python |
| Latence 2-10s | Pas utilisable temps réel | Mode hors-ligne, batch quotidien |
| RAM 8-12 GB | Impact sur VPS | Machine dédiée ou scheduling |

### Architecture de décision finale

```
DONNÉES BRUTES (30s → 1h)
├── WebSocket Prices (Binance)
├── Fear & Greed API (alternative.me)
├── MVRV (CoinGecko)
└── RSI / EMA / VWAP (calculés localement)
    │
    ▼
COUCHE D'ANALYSE (Hors ligne)
├── RSI Double Filtre (<20 sur 15m+4h)
├── EMA200 Trend Filter
└── LLM Sentiment (DeepSeek) — advisory only
    │
    ▼
DÉCISION (Règles codées en dur)
├── IF RSI_15m < 20 AND RSI_4h < 20 AND FGI < 30:
│   DCA_multiplier = 2.0, grid_aggressiveness = 1.5
├── IF FGI > 75:
│   sell_5_percent(), suspend_grid()
├── IF MVRV < 1.0:
│   DCA_multiplier = max(current, 1.5)
└── Multiplier limité : [0.25x, 2.5x]
    │
    ▼
EXÉCUTION (WebSocket + REST)
├── Ordres DCA (REST API)
├── Ordres Grid (REST API)
└── Risk Manager (coupe-circuit : daily loss > 5% → STOP)
```

---

## SESSION 3 — PRODUCTION, FISCALITÉ, MONITORING
*(En cours de génération par DeepSeek — sera complété)*

### 1. Conformité fiscale France ✅
- **Flat tax 30% (PFU)** sur les plus-values crypto (12.8% IR + 17.2% prélèvements sociaux)
- **Formulaire 3916-bis** obligatoire pour déclarer compte Binance (siège Seychelles). Amende 750€ par compte non déclaré
- **DAC8** en vigueur depuis 1er janvier 2026 : reporting automatique des exchanges vers fisc, échange données UE, gel de compte possible
- **Crypto→crypto n'est PAS imposable** en France pour les particuliers. Événement taxable = conversion en fiat (EUR) ou achat bien/service
- **Méthode FIFO** (First In, First Out) pour calcul coût d'acquisition
- **Format logs** : `timestamp,exchange,symbol,side,quantity,price,fee_asset,fee_amount,quote_value,realized_pnl,position_id`
- **Optimisation fiscale** : cash flow rebalancing, loss harvesting, partial rebalancing

### 2. Testnet & Paper Trading ✅
- Binance Testnet : `testnet.binance.vision`
- Min 200 trades sur testnet avant capital réel
- Critères validation : Sharpe > 1.0, MDD < 50%, Profit Factor > 1.2

### 3. Portfolio Rebalancing ✅
- Cash flow rebalancing : utiliser les dépôts mensuels pour acheter les actifs sous-pondérés
- Loss harvesting : vendre les positions perdantes pour compenser les gains
- Partial rebalancing : ne corriger que la moitié de la dérive

### 4. Market Regime Detection ✅
- Approche multi-factorielle "Crypto Grail" : ADX, volatilité historique, EMA slopes
- Adaptation stratégie par régime : bull (grid élargi), bear (DCA renforcé, grid suspendu), sideways (grid optimal)

### 5. Architecture Production ✅
- asyncio + WebSocket + Queue + SQLite avec BEGIN IMMEDIATE + logs JSON
- Circuit breaker avec backoff exponentiel et auto-reset après 1h
- JSON Lines logging avec RotatingFileHandler
- État persisté en SQLite pour restart propre

### 6. Monitoring & Alertes ✅
- Dashboard Streamlit (Total Trades, Win Rate, Net P&L, status actif/inactif)
- P&L chart cumulatif + recent trades
- Alertes Telegram sur seuils critiques (Daily P&L < -5% → alerte, < -10% → stop)

### 7. Sécurité Opérationnelle ✅
- Idempotency keys pour chaque ordre (éviter double spending)
- asyncio.Lock pour sections critiques
- TTL sur prix (données périmées = pas d'ordre)
- Isolation Docker recommandée pour production

---

## SESSION 5 — EDGE CASES, CRASH RECOVERY & STRESS TESTING ✅

### Codes erreur Binance — Dictionnaire exhaustif
- `-1021` timestamp → retry_adjust_time
- `-1015` rate limit → wait (exponential backoff)
- `-2010` insufficient balance → alert + stop symbol
- `-1001` disconnected → reconnect WebSocket
- `-1003` too many requests → throttle (semaphore)
- `-3000` server internal → retry max 3x
- `-3001` symbol not tradable → stop symbol

### Partial Fills
- Track fill ratio, cancel rest after timeout configurable
- Recalcul position size basé sur qty réellement remplie

### Crash Recovery — Algorithme
1. Lire état SQLite local
2. fetch_open_orders() + fetch_orders(since=last_known)
3. Réconcilier : local vs exchange
4. Traiter orphan orders (identifiés par clientOrderId prefix)

### Flash Crashes
- Circuit breaker + "pause and assess" mode (5min cooldown)
- Différencier flash crash (V-recovery) vs bear trend (EMA slope analysis)

### Memory Leaks
- Circular buffers pour historique (deque, maxlen)
- Purge DataFrames > 24h, monitor RAM avec psutil
- Graceful restart si RAM > 1.5 Go

### SQLite Backup
- WAL mode, backup horaire (.db copy), conserver 3 dernières
- Checksum SHA-256 sur trades critiques

### 5 Scénarios catastrophe documentés avec réponses attendues

---

## SESSION 6 — OPTIMISATION PERFORMANCE & SCALABILITÉ ✅

### Benchmarks M4 (24 Go)

| Opération | Avant optim | Après optim |
|---|---|---|
| Mémoire (bot seul) | ~800 Mo | ~300 Mo |
| Temps démarrage | 15-20 s | < 5 s |
| Latence moyenne ordre | 250 ms | 50 ms (serveur réel) |
| Calcul RSI/EMA temps réel | 15 ms | 0.1 ms |
| Insertion SQLite | 200/s | 1000/s |
| CPU (inactif) | 5-10% | < 2% |

### Points clés
- **Profiling** : py-spy en production (low overhead), Scalene pour mémoire/CPU
- **Mémoire** : polars ou numpy pur au lieu de pandas, float32 au lieu de float64, deque pour buffers
- **Asyncio** : TaskGroup (Python 3.11+), supervision tree, cancellation scopes
- **Latence** : ccxt.pro gère connection pooling via aiohttp, DNS cache OS-level
- **SQLite** : WAL mode, PRAGMA synchronous=NORMAL, page_size=4096, aiosqlite
- **Indicateurs** : Algorithmes incrémentaux (rolling RSI/EMA sans recalcul complet)
- **Startup** : Precompute indicateurs au shutdown, reload au startup, asyncio.gather pour paralléliser
- **Multi-paire** : WebSocket multiplexé unique (`wss://stream.binance.com:9443/ws/btcusdt@ticker/ethusdt@ticker/...`)

---

## SESSION 7-10 — EN COURS
- Session 7 : Psychologie du trading & discipline automatisée
- Session 8 : Analyse exchanges & diversification
- Session 9 : ML pour trading
- Session 10 : Architecture finale + blueprint

---

## STACK TECHNIQUE

| Composant | Technologie |
|---|---|
| Langage | Python 3.10+ |
| Exchange | Binance via ccxt |
| LLM local | DeepSeek-R1 8B via Ollama |
| Base de données | SQLite (état, historique, logs) |
| WebSocket | ccxt Pro ou websockets |
| Indicateurs | pandas-ta ou ta-lib |
| Backtesting | Backtrader / VectorBT |
| Alertes | Telegram Bot API / macOS notifications |
| Logs | JSON Lines (structuré) avec rotation |
| Tests | pytest + Binance Testnet |

## STRUCTURE PROJET (CryptoMind)

```
~/Desktop/cryptomind/
├── config/
│   ├── config.yaml          # Configuration principale
│   ├── network_policies.yaml # Politiques réseau
│   └── strategies.yaml       # Paramètres stratégies
├── core/
│   ├── brain.py              # Orchestrateur principal
│   ├── event_bus.py          # Bus d'événements
│   └── state.py              # État persisté SQLite
├── data/
│   ├── ingestion.py          # WebSocket + REST data feeds
│   ├── indicators.py         # RSI, EMA, VWAP, ATR
│   └── onchain.py            # MVRV, Fear & Greed
├── strategies/
│   ├── dca.py                # Stratégie DCA modulée
│   ├── grid.py               # Grid trading adaptatif
│   └── rebalancer.py         # Portfolio rebalancing
├── risk/
│   ├── manager.py            # Position sizing, stop-loss
│   ├── circuit_breaker.py    # Coupe-circuit
│   └── regime_detector.py    # Bull/bear/sideways
├── execution/
│   ├── order_manager.py      # Queue d'ordres, retry
│   └── binance_client.py     # Wrapper ccxt
├── llm/
│   ├── analyst.py            # DeepSeek via Ollama
│   ├── sentiment.py          # Analyse news
│   └── reporter.py           # Rapports quotidiens
├── monitoring/
│   ├── dashboard.py          # Métriques temps réel
│   ├── alerts.py             # Telegram + macOS
│   └── health.py             # Health checks
├── fiscal/
│   ├── logger.py             # Logs immutables JSONL
│   ├── calculator.py         # Plus-values, P&L
│   └── export.py             # Export DAC8 / 3916-bis
├── tests/
│   ├── test_strategies.py
│   ├── test_risk.py
│   └── test_execution.py
├── main.py                   # Point d'entrée
├── requirements.txt
└── README.md
```

---

## RÈGLES DE DÉVELOPPEMENT
1. **Train before code** — Toutes les sessions DeepSeek terminées avant d'écrire du code
2. **Testnet first** — Jamais d'argent réel avant validation testnet (min 200 trades)
3. **100% local** — Seules connexions sortantes : Binance API + alternative.me + CoinGecko
4. **LLM = advisory** — Jamais de décision automatique par le LLM
5. **Logs immutables** — Chaque opération loggée pour conformité fiscale
6. **Risk first** — Le risk manager peut tout couper, aucun override possible
