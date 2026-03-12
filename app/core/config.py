"""
Configuration de l'application.
Gère le chargement depuis un fichier YAML et fournit des objets de configuration typés.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class AppConfig:
    name: str = "Agent Lucide"
    version: str = "4.0"
    data_dir: str = "./data"
    docs_dir: str = "./Lucid_Docs"
    logs_dir: str = "./logs"


@dataclass
class LLMModelConfig:
    name: str
    max_tokens: int = 2048
    temperature: float = 0.7


@dataclass
class LLMConfig:
    host: str = "http://localhost:11434"
    default_model: str = "qwen2.5:7b"
    timeout: int = 60
    retry_attempts: int = 2
    retry_delay: float = 1.0
    keep_alive: int = -1
    models: Dict[str, LLMModelConfig] = field(default_factory=dict)


@dataclass
class MetricsConfig:
    enabled: bool = True
    port: int = 8000
    memory_interval: int = 60


@dataclass
class MemoryConfig:
    max_episodic: int = 10000
    working_capacity: int = 10
    consolidation_interval: int = 3600
    auto_consolidate: bool = True
    max_short_term: int = 5
    max_long_term: int = 3


@dataclass
class ElasticityConfig:
    min_workers: int = 1
    max_workers: int = 5
    cpu_threshold: float = 70.0
    memory_threshold: float = 80.0
    cooldown: int = 60


@dataclass
class RAGConfig:
    enabled: bool = True
    chunk_size: int = 500
    chunk_overlap: int = 50
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    vector_db_path: str = "./data/rag_index"
    max_sources: int = 3  # <-- AJOUT


@dataclass
class ActionsConfig:
    word_output_dir: str = "./Lucid_Docs"
    visible_actions: bool = True
    move_duration: float = 0.5
    type_interval: float = 0.05
    use_spell_check: bool = False
    use_applescript_for_typing: bool = False
    use_paste_for_typing: bool = True


@dataclass
class VisionConfig:
    enabled: bool = False
    model: str = "moondream:latest"
    temp_dir: str = "./data/vision_temp"


@dataclass
class ApiKeysConfig:
    news_api_key: str = ""


@dataclass
class P2PConfig:
    enabled: bool = True
    port: int = 9000
    bootstrap_peers: List[str] = field(default_factory=list)


@dataclass
class CyberConfig:
    error_threshold: int = 3
    time_window: int = 300
    severity_threshold: float = 0.5
    quarantine_duration: int = 3600


@dataclass
class HealerConfig:
    quarantine_dir: str = "~/AgentLucide/quarantine"
    lures_dir: str = "~/AgentLucide/lures"
    auto_quarantine: bool = True
    stealth_mode: bool = False
    yara_rules_path: str = "~/.agent_lucide/yara_rules.yar"
    malicious_hashes_path: str = "~/.agent_lucide/malicious_hashes.txt"
    scan_threshold: float = 0.5
    lure_ttl: int = 86400


@dataclass
class PlannerConfig:
    max_plan_steps: int = 5


@dataclass
class Config:
    app: AppConfig = field(default_factory=AppConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    elasticity: ElasticityConfig = field(default_factory=ElasticityConfig)
    rag: RAGConfig = field(default_factory=RAGConfig)
    actions: ActionsConfig = field(default_factory=ActionsConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    api_keys: ApiKeysConfig = field(default_factory=ApiKeysConfig)
    p2p: P2PConfig = field(default_factory=P2PConfig)
    cyber: CyberConfig = field(default_factory=CyberConfig)
    healer: HealerConfig = field(default_factory=HealerConfig)
    planner: PlannerConfig = field(default_factory=PlannerConfig)

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        if path is None:
            # Chercher config.yaml dans le répertoire courant
            base = Path(__file__).parent.parent.parent
            path = base / "config.yaml"
        else:
            path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"Fichier de configuration introuvable: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Construire les objets de configuration
        config = cls()

        # App
        app_data = data.get("app", {})
        config.app = AppConfig(**app_data)

        # LLM
        llm_data = data.get("llm", {})
        models_data = llm_data.pop("models", {})
        models = {}
        for key, model_conf in models_data.items():
            models[key] = LLMModelConfig(**model_conf)
        config.llm = LLMConfig(models=models, **llm_data)

        # Metrics
        metrics_data = data.get("metrics", {})
        config.metrics = MetricsConfig(**metrics_data)

        # Memory
        memory_data = data.get("memory", {})
        config.memory = MemoryConfig(**memory_data)

        # Elasticity
        elasticity_data = data.get("elasticity", {})
        config.elasticity = ElasticityConfig(**elasticity_data)

        # RAG
        rag_data = data.get("rag", {})
        config.rag = RAGConfig(**rag_data)

        # Actions
        actions_data = data.get("actions", {})
        config.actions = ActionsConfig(**actions_data)

        # Vision
        vision_data = data.get("vision", {})
        config.vision = VisionConfig(**vision_data)

        # API Keys
        api_keys_data = data.get("api_keys", {})
        config.api_keys = ApiKeysConfig(**api_keys_data)

        # P2P
        p2p_data = data.get("p2p", {})
        config.p2p = P2PConfig(**p2p_data)

        # Cyber
        cyber_data = data.get("cyber", {})
        config.cyber = CyberConfig(**cyber_data)

        # Healer
        healer_data = data.get("healer", {})
        config.healer = HealerConfig(**healer_data)

        # Planner
        planner_data = data.get("planner", {})
        config.planner = PlannerConfig(**planner_data)

        return config