"""Configuration centrale du bot Albion PPCF.

Toutes les valeurs sensibles viennent des variables d'environnement.
Les noms de rôles/salons correspondent à la structure Discord décrite pour la guilde.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
DATA_DIR: Final[Path] = PROJECT_ROOT / "data"
BACKUP_DIR: Final[Path] = PROJECT_ROOT / "backups"


def _int_env(name: str, default: int | None = None) -> int | None:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return int(value)


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    """Paramètres applicatifs chargés depuis l'environnement."""

    discord_token: str = field(default_factory=lambda: os.getenv("DISCORD_TOKEN", ""))
    guild_id: int | None = field(default_factory=lambda: _int_env("GUILD_ID"))
    albion_guild_id: str = field(default_factory=lambda: os.getenv("ALBION_GUILD_ID", ""))
    albion_guild_name: str = field(default_factory=lambda: os.getenv("ALBION_GUILD_NAME", ""))

    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    sqlite_path: str = field(default_factory=lambda: os.getenv("SQLITE_PATH", "./data/albion_guild_bot.db"))

    albion_api_base_url: str = field(
        default_factory=lambda: os.getenv(
            "ALBION_API_BASE_URL", "https://gameinfo.albiononline.com/api/gameinfo"
        )
    )
    albion_market_base_url: str = field(
        default_factory=lambda: os.getenv(
            "ALBION_MARKET_BASE_URL", "https://www.albion-online-data.com/api/v2/stats"
        )
    )
    albion_tools_base_url: str = field(default_factory=lambda: os.getenv("ALBION_TOOLS_BASE_URL", "https://albion.tools"))

    command_prefix: str = field(default_factory=lambda: os.getenv("COMMAND_PREFIX", "!"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    sync_commands_on_start: bool = field(default_factory=lambda: _bool_env("SYNC_COMMANDS_ON_START", True))
    test_mode: bool = field(default_factory=lambda: _bool_env("TEST_MODE", True))
    default_timezone: str = field(default_factory=lambda: os.getenv("DEFAULT_TIMEZONE", "UTC"))

    alerts_channel_id: int | None = field(default_factory=lambda: _int_env("ALERTS_CHANNEL_ID"))
    backup_channel_id: int | None = field(default_factory=lambda: _int_env("BACKUP_CHANNEL_ID"))


settings = Settings()

# Noms canoniques des rôles Discord.
ROLE_NAMES: Final[dict[str, str]] = {
    "guild_master": "🟠 Maître de Guilde",
    "war_lord": "🟡 Seigneur de Guerre",
    "grand_treasurer": "🔴 Grand Trésorier",
    "officer": "🟢 Officier",
    "knight": "🟣 Chevalier",
    "recruit": "🔵 Recrue",
    "unverified": "⚪ Non vérifié",
    "tank": "🛡️ Tank",
    "dps": "⚔️ DPS",
    "healer": "💚 Healer",
    "support": "🌿 Support",
    "lfg": "👥 recherche-de-groupe",
    "deployment": "🐺 déploiement",
}

CLASS_ROLE_KEYS: Final[tuple[str, ...]] = ("tank", "dps", "healer", "support", "lfg", "deployment")
ADMIN_ROLE_KEYS: Final[tuple[str, ...]] = ("guild_master",)
ORDER_MANAGER_ROLE_KEYS: Final[tuple[str, ...]] = ("war_lord", "grand_treasurer")
OFFICER_ROLE_KEYS: Final[tuple[str, ...]] = ("guild_master", "war_lord", "grand_treasurer", "officer")

# Noms canoniques des salons Discord.
CHANNEL_NAMES: Final[dict[str, str]] = {
    "rules": "📖 règles",
    "new_guide": "🎓 guide-nouveau",
    "roles": "🎭 rôles",
    "announcements": "📢 annonce",
    "leaderboard": "🏆 leaderboard",
    "priority_orders": "🎯 ordre-prioritaire",
    "past_orders": "📜 ordres-passés",
    "officer_discussion": "💬 discussion-officiers",
    "guild_management": "📋 gestion-guilde",
    "bot_alerts": "🚨 alertes-bot",
    "ticket_logs": "🎫 logs-tickets",
    "sql_backup": "💾 backup-sql",
    "treasury": "💰 trésorerie",
    "history": "📜 historique",
    "declaration": "✉️ declaration",
    "general": "💬 général",
    "flex": "💪 flex",
    "quests": "📋 tableau-des-quêtes",
    "lfg": "👥 recherche-de-groupe",
    "arrival_departure": "🏰 arrivé-départ",
    "bot_commands": "🤖 commandes-bot",
    "deployment": "🐺 déploiement",
    "promotion": "🏅 promotion",
    "battlefield": "💀 champ-de-bataille",
    "market_commands": "🛒 commandes-marché",
    "price_alerts": "🚨 alertes-prix",
    "craft_requests": "🔨 demandes-craft-ressources",
    "guild_trade": "🤝 achat-vente-guilde",
}

# TTL cache recommandés.
CACHE_TTL_SECONDS: Final[dict[str, int]] = {
    "market_prices": 600,
    "player_info": 3600,
    "recent_kills": 300,
    "item_icons": 86400,
}
