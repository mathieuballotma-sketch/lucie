"""
Profils optimisés pour chaque modèle LLM installé.

Chaque profil contient :
- system_prompt adapté aux capacités réelles du modèle
- Paramètres Ollama optimisés (num_ctx, temperature, num_predict)
- Capacités documentées (forces, faiblesses)
- Instructions de fallback si réponse invalide

Basé sur l'inventaire réel : ollama list + ollama show pour chaque modèle.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class OptimizedProfile:
    """Profil complet d'un modèle avec system prompt et paramètres optimisés."""

    # Identité
    name: str
    family: str  # qwen2, llama, gemma2, etc.
    parameters: str  # "0.5B", "7B", "14B", etc.
    category: str  # code, reasoning, writing, vision, quick, balanced, quality, mathieu

    # System prompt optimisé
    system_prompt: str

    # Paramètres Ollama
    num_ctx: int = 4096
    temperature: float = 0.7
    num_predict: int = 512
    priority: int = 0

    # Températures par type de tâche
    temp_by_task: Dict[str, float] = field(default_factory=dict)

    # Capacités documentées
    capabilities: Dict[str, int] = field(default_factory=dict)
    # vitesse (1-5), raisonnement (1-5), francais (1-5), code (1-5)

    # Instruction de fallback
    fallback_instruction: str = ""

    def get_temperature(self, task_type: Optional[str] = None) -> float:
        """Retourne la température optimale pour un type de tâche."""
        if task_type and task_type in self.temp_by_task:
            return self.temp_by_task[task_type]
        return self.temperature

    def to_options(self, task_type: Optional[str] = None,
                   override_temp: Optional[float] = None,
                   override_max_tokens: Optional[int] = None) -> Dict[str, Any]:
        """Retourne les options Ollama optimisées."""
        return {
            "num_ctx": self.num_ctx,
            "temperature": (override_temp if override_temp is not None
                            else self.get_temperature(task_type)),
            "num_predict": (override_max_tokens if override_max_tokens is not None
                            else self.num_predict),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# MODÈLES PETITS (0.5B - 3B) — Instructions ultra-courtes, une tâche à la fois
# ═══════════════════════════════════════════════════════════════════════════════

_PROFILE_QWEN_05B = OptimizedProfile(
    name="qwen2.5:0.5b",
    family="qwen2",
    parameters="0.5B",
    category="quick",
    system_prompt=(
        "Agent rapide. FR, 1 phrase max. "
        "Jamais d'invention."
    ),
    num_ctx=1024,
    temperature=0.3,
    num_predict=64,
    priority=8,
    temp_by_task={
        "quick": 0.2,
        "code": 0.1,
        "writing": 0.5,
    },
    capabilities={"vitesse": 5, "raisonnement": 1, "francais": 2, "code": 1},
    fallback_instruction="Si tu ne sais pas, dis 'Je ne sais pas' sans inventer.",
)

_PROFILE_QWEN_3B = OptimizedProfile(
    name="qwen2.5:3b",
    family="qwen2",
    parameters="3B",
    category="quick",
    system_prompt=(
        "Agent local rapide. FR obligatoire. 1-3 phrases. "
        "Code: code seul. Incertain: dis-le."
    ),
    num_ctx=2048,
    temperature=0.4,
    num_predict=256,
    priority=10,
    temp_by_task={
        "quick": 0.2,
        "code": 0.15,
        "writing": 0.6,
        "reasoning": 0.3,
    },
    capabilities={"vitesse": 5, "raisonnement": 2, "francais": 3, "code": 2},
    fallback_instruction="Si la question est trop complexe, résume ce que tu comprends et propose de reformuler.",
)

_PROFILE_LLAMA32_3B = OptimizedProfile(
    name="llama3.2:3b",
    family="llama",
    parameters="3B",
    category="quick",
    system_prompt=(
        "Fast local agent. Respond FR. 1-3 sentences. "
        "Code: code only. Unsure: state it."
    ),
    num_ctx=2048,
    temperature=0.4,
    num_predict=256,
    priority=7,
    temp_by_task={
        "quick": 0.2,
        "code": 0.15,
        "writing": 0.6,
    },
    capabilities={"vitesse": 5, "raisonnement": 2, "francais": 2, "code": 2},
    fallback_instruction="If the question is too complex, summarize what you understand.",
)

# ═══════════════════════════════════════════════════════════════════════════════
# MODÈLES MOYENS (7B - 9B) — Instructions structurées, exemples inclus
# ═══════════════════════════════════════════════════════════════════════════════

_PROFILE_QWEN_7B = OptimizedProfile(
    name="qwen2.5:7b",
    family="qwen2",
    parameters="7.6B",
    category="balanced",
    system_prompt=(
        "Lucie, IA macOS. FR obligatoire. "
        "Structuré en puces. Code: complet. "
        "Questions: 2-5 phrases. Incertain: signale."
    ),
    num_ctx=4096,
    temperature=0.6,
    num_predict=512,
    priority=9,
    temp_by_task={
        "quick": 0.3,
        "code": 0.2,
        "writing": 0.7,
        "reasoning": 0.4,
    },
    capabilities={"vitesse": 4, "raisonnement": 3, "francais": 4, "code": 3},
    fallback_instruction="Si ta réponse semble incomplète, ajoute '...(suite possible)' à la fin.",
)

_PROFILE_MISTRAL = OptimizedProfile(
    name="mistral:latest",
    family="llama",
    parameters="7.2B",
    category="balanced",
    system_prompt=(
        "Lucie, IA française macOS. FR natif fluide. "
        "Code: commenté FR. Analyse: points clés. "
        "Zéro répétition."
    ),
    num_ctx=4096,
    temperature=0.65,
    num_predict=512,
    priority=7,
    temp_by_task={
        "quick": 0.3,
        "code": 0.2,
        "writing": 0.75,
        "reasoning": 0.4,
    },
    capabilities={"vitesse": 4, "raisonnement": 3, "francais": 5, "code": 3},
    fallback_instruction="Si la demande est ambiguë, propose 2 interprétations possibles.",
)

_PROFILE_DEEPSEEK_R1 = OptimizedProfile(
    name="deepseek-r1:7b",
    family="qwen2",
    parameters="7.6B",
    category="reasoning",
    system_prompt=(
        "Expert raisonnement. FR. "
        "<think>étapes</think> obligatoire. "
        "Calculs: montre étapes. Analyse: pour/contre. "
        "Vérifie avant réponse."
    ),
    num_ctx=8192,
    temperature=0.3,
    num_predict=1024,
    priority=10,
    temp_by_task={
        "reasoning": 0.2,
        "code": 0.15,
        "writing": 0.5,
        "quick": 0.3,
    },
    capabilities={"vitesse": 2, "raisonnement": 5, "francais": 3, "code": 3},
    fallback_instruction="Si le raisonnement aboutit à une incertitude, exprime le niveau de confiance en pourcentage.",
)

_PROFILE_DEEPSEEK_CODER = OptimizedProfile(
    name="deepseek-coder:6.7b",
    family="llama",
    parameters="7B",
    category="code",
    system_prompt=(
        "Senior Python dev. Code seul. Types obligatoires. "
        "PEP8. async/await. No bare except. "
        "Stack: Py3.13/asyncio/Ollama/SQLite/FAISS/pydantic.v1."
    ),
    num_ctx=4096,
    temperature=0.15,
    num_predict=1024,
    priority=8,
    temp_by_task={
        "code": 0.1,
        "reasoning": 0.3,
        "writing": 0.5,
    },
    capabilities={"vitesse": 3, "raisonnement": 3, "francais": 1, "code": 4},
    fallback_instruction="If the code request is unclear, generate the most likely interpretation with a comment explaining the assumption.",
)

_PROFILE_GEMMA2 = OptimizedProfile(
    name="gemma2:9b",
    family="gemma2",
    parameters="9.2B",
    category="writing",
    system_prompt=(
        "Rédacteur expert FR. Emails/lettres/rapports/correction. "
        "Ton adapté au contexte. Texte direct. "
        "Zéro anglicisme."
    ),
    num_ctx=8192,
    temperature=0.5,
    num_predict=1024,
    priority=10,
    temp_by_task={
        "writing": 0.5,
        "quick": 0.4,
        "reasoning": 0.4,
        "code": 0.2,
    },
    capabilities={"vitesse": 3, "raisonnement": 3, "francais": 5, "code": 2},
    fallback_instruction="Si le contexte manque, demande une précision sur le ton souhaité (formel/informel) et le destinataire.",
)

_PROFILE_LLAMA3 = OptimizedProfile(
    name="llama3:latest",
    family="llama",
    parameters="8B",
    category="balanced",
    system_prompt=(
        "Lucie, IA macOS. FR. Direct, structuré. "
        "Code: fonctionnel seul. Questions: 3-5 phrases."
    ),
    num_ctx=4096,
    temperature=0.65,
    num_predict=512,
    priority=5,
    temp_by_task={
        "quick": 0.3,
        "code": 0.2,
        "writing": 0.7,
        "reasoning": 0.4,
    },
    capabilities={"vitesse": 4, "raisonnement": 3, "francais": 3, "code": 3},
    fallback_instruction="Si tu n'es pas sûr de la réponse, donne ta meilleure estimation en le signalant.",
)

_PROFILE_LLAMA3_INSTRUCT = OptimizedProfile(
    name="llama3:8b-instruct-q4_K_M",
    family="llama",
    parameters="8B",
    category="balanced",
    system_prompt=(
        "Lucie, IA macOS. FR. Exécute instructions précis. "
        "Code: typé fonctionnel. Questions: 2-5 phrases."
    ),
    num_ctx=4096,
    temperature=0.6,
    num_predict=512,
    priority=4,
    temp_by_task={
        "quick": 0.3,
        "code": 0.2,
        "writing": 0.7,
        "reasoning": 0.4,
    },
    capabilities={"vitesse": 4, "raisonnement": 3, "francais": 3, "code": 3},
    fallback_instruction="En cas de doute, suis l'interprétation la plus littérale de l'instruction.",
)

# ═══════════════════════════════════════════════════════════════════════════════
# MODÈLES GRANDS (14B - 22B) — Instructions riches, auto-vérification
# ═══════════════════════════════════════════════════════════════════════════════

_PROFILE_QWEN_14B = OptimizedProfile(
    name="qwen2.5:14b",
    family="qwen2",
    parameters="14.8B",
    category="quality",
    system_prompt=(
        "Lucie, IA qualité macOS. FR impeccable. "
        "Raisonnement multi-étapes. Code: typé+erreurs. "
        "Analyse: tous angles. Vérifie avant réponse. "
        "Zéro remplissage."
    ),
    num_ctx=8192,
    temperature=0.55,
    num_predict=1024,
    priority=10,
    temp_by_task={
        "code": 0.15,
        "reasoning": 0.3,
        "writing": 0.7,
        "quick": 0.4,
    },
    capabilities={"vitesse": 2, "raisonnement": 4, "francais": 4, "code": 4},
    fallback_instruction="Si ta réponse nécessite des connaissances que tu n'as pas, indique précisément ce qui te manque et propose une alternative.",
)

_PROFILE_CODESTRAL = OptimizedProfile(
    name="codestral:latest",
    family="llama",
    parameters="22.2B",
    category="code",
    system_prompt=(
        "Codestral, code expert. Code seul. "
        "Types+async obligatoires. Guard Optional. "
        "No bare except. pydantic.v1. No MetricsCollector. "
        "Stack: Py3.13/asyncio/PyObjC/Ollama/SQLite/FAISS/EventBus."
    ),
    num_ctx=8192,
    temperature=0.15,
    num_predict=2048,
    priority=10,
    temp_by_task={
        "code": 0.1,
        "reasoning": 0.3,
        "writing": 0.5,
        "quick": 0.3,
    },
    capabilities={"vitesse": 1, "raisonnement": 4, "francais": 2, "code": 5},
    fallback_instruction="If the code request is ambiguous, generate the safest interpretation and add a TODO comment for the ambiguous part.",
)

_PROFILE_GPT_OSS = OptimizedProfile(
    name="gpt-oss:20b",
    family="gptoss",
    parameters="20.9B",
    category="quality",
    system_prompt=(
        "Lucie, IA avancée macOS+thinking. FR pro. "
        "Décompose, vérifie, incertitudes explicites. "
        "Code: typé production. Zéro remplissage."
    ),
    num_ctx=8192,
    temperature=0.6,
    num_predict=1024,
    priority=8,
    temp_by_task={
        "code": 0.15,
        "reasoning": 0.3,
        "writing": 0.7,
        "quick": 0.4,
    },
    capabilities={"vitesse": 1, "raisonnement": 5, "francais": 3, "code": 4},
    fallback_instruction="Utilise ta capacité thinking pour vérifier ta réponse avant de la donner.",
)

# ═══════════════════════════════════════════════════════════════════════════════
# MODÈLES VISION — Description structurée imposée
# ═══════════════════════════════════════════════════════════════════════════════

_PROFILE_LLAVA = OptimizedProfile(
    name="llava:latest",
    family="llama",
    parameters="7B",
    category="vision",
    system_prompt=(
        "Analyse image FR. "
        "Format: SUJET|DÉTAILS|TEXTE|CONTEXTE|ACTION. "
        "Factuel uniquement."
    ),
    num_ctx=2048,
    temperature=0.4,
    num_predict=512,
    priority=10,
    temp_by_task={
        "vision": 0.3,
        "quick": 0.3,
    },
    capabilities={"vitesse": 3, "raisonnement": 2, "francais": 3, "code": 1},
    fallback_instruction="Si l'image est floue ou ambiguë, décris ce que tu peux identifier avec certitude.",
)

_PROFILE_MOONDREAM = OptimizedProfile(
    name="moondream:latest",
    family="phi2",
    parameters="1B",
    category="vision",
    system_prompt=(
        "Image→FR. Subject|Text|Context. "
        "Brief, factual."
    ),
    num_ctx=2048,
    temperature=0.3,
    num_predict=256,
    priority=5,
    temp_by_task={
        "vision": 0.2,
    },
    capabilities={"vitesse": 5, "raisonnement": 1, "francais": 1, "code": 0},
    fallback_instruction="If unsure, describe only what you can clearly see.",
)

# ═══════════════════════════════════════════════════════════════════════════════
# MODÈLE PERSONNALISÉ — Contexte Mathieu complet
# ═══════════════════════════════════════════════════════════════════════════════

_PROFILE_MATHIEU = OptimizedProfile(
    name="mathieu-ia:latest",
    family="qwen2",
    parameters="7.6B",
    category="mathieu",
    system_prompt=(
        "Assistant perso Mathieu. Tutoiement. "
        "FR direct, zéro fluff. Dev Lucie: Python/asyncio/Ollama/PyObjC. "
        "Solutions concrètes, pas descriptions."
    ),
    num_ctx=4096,
    temperature=0.7,
    num_predict=512,
    priority=10,
    temp_by_task={
        "quick": 0.4,
        "code": 0.2,
        "writing": 0.75,
        "reasoning": 0.4,
    },
    capabilities={"vitesse": 4, "raisonnement": 3, "francais": 4, "code": 3},
    fallback_instruction="Si tu ne connais pas un détail sur Mathieu, demande-lui plutôt que d'inventer.",
)

# ═══════════════════════════════════════════════════════════════════════════════
# EMBEDDINGS — Pas de system prompt (pas de chat)
# ═══════════════════════════════════════════════════════════════════════════════

_PROFILE_MXBAI = OptimizedProfile(
    name="mxbai-embed-large:latest",
    family="bert",
    parameters="335M",
    category="embedding",
    system_prompt="",
    num_ctx=512,
    temperature=0.0,
    num_predict=0,
    priority=10,
    capabilities={"vitesse": 5, "raisonnement": 0, "francais": 0, "code": 0},
)

_PROFILE_NOMIC = OptimizedProfile(
    name="nomic-embed-text:latest",
    family="nomic",
    parameters="137M",
    category="embedding",
    system_prompt="",
    num_ctx=512,
    temperature=0.0,
    num_predict=0,
    priority=5,
    capabilities={"vitesse": 5, "raisonnement": 0, "francais": 0, "code": 0},
)


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRE CENTRAL — Accès par nom de modèle
# ═══════════════════════════════════════════════════════════════════════════════

MODEL_PROFILES: Dict[str, OptimizedProfile] = {
    p.name: p for p in [
        # Petits
        _PROFILE_QWEN_05B,
        _PROFILE_QWEN_3B,
        _PROFILE_LLAMA32_3B,
        # Moyens
        _PROFILE_QWEN_7B,
        _PROFILE_MISTRAL,
        _PROFILE_DEEPSEEK_R1,
        _PROFILE_DEEPSEEK_CODER,
        _PROFILE_GEMMA2,
        _PROFILE_LLAMA3,
        _PROFILE_LLAMA3_INSTRUCT,
        # Grands
        _PROFILE_QWEN_14B,
        _PROFILE_CODESTRAL,
        _PROFILE_GPT_OSS,
        # Vision
        _PROFILE_LLAVA,
        _PROFILE_MOONDREAM,
        # Personnalisé
        _PROFILE_MATHIEU,
        # Embeddings
        _PROFILE_MXBAI,
        _PROFILE_NOMIC,
    ]
}


def get_profile(model_name: str) -> Optional[OptimizedProfile]:
    """Retourne le profil optimisé d'un modèle, ou None si inconnu."""
    return MODEL_PROFILES.get(model_name)


def get_system_prompt(model_name: str) -> Optional[str]:
    """Retourne le system prompt optimisé pour un modèle, ou None si inconnu/embedding."""
    profile = MODEL_PROFILES.get(model_name)
    if profile and profile.system_prompt:
        return profile.system_prompt
    return None


def get_capabilities_summary() -> Dict[str, Dict[str, int]]:
    """Retourne un résumé des capacités de tous les modèles (hors embeddings)."""
    return {
        name: profile.capabilities
        for name, profile in MODEL_PROFILES.items()
        if profile.category != "embedding"
    }
