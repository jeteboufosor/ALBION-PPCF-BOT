# Albion PPCF Bot Discord

Bot Discord async pour une guilde Albion Online basée à Fort Sterling.

Ce dépôt est développé en 7 phases. La **Phase 1 — Fondations** met en place l'architecture, la configuration, la base de données async, les modèles, les utilitaires et les clients API.

## Stack

- Python 3.11+
- discord.py 2.x avec slash commands
- SQLAlchemy 2.0 async (`Mapped[]`, `mapped_column()`)
- SQLite local via `aiosqlite`
- PostgreSQL Railway via `asyncpg`
- httpx
- APScheduler
- python-dotenv

## Structure

```text
bot/
├── main.py
├── config.py
├── cogs/
├── services/
│   ├── albion_api.py
│   ├── market_api.py
│   └── item_service.py
├── database/
│   ├── engine.py
│   ├── models.py
│   └── crud.py
├── tasks/
└── utils/
    ├── cache.py
    ├── embeds.py
    ├── permissions.py
    └── helpers.py
```

## Installation locale

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
cp .env.example .env
```

Renseignez au minimum dans `.env` :

```env
DISCORD_TOKEN=token_du_bot
GUILD_ID=id_du_serveur_discord
ALBION_GUILD_ID=id_de_la_guilde_albion
```

En local, laissez `DATABASE_URL` vide. Le bot utilisera automatiquement :

```text
sqlite+aiosqlite:///./data/albion_guild_bot.db
```

## Lancer le bot

```bash
python -m bot.main
```

Au démarrage, le bot :

1. charge les variables `.env`,
2. détecte SQLite ou PostgreSQL,
3. crée les tables manquantes,
4. charge automatiquement les cogs présents dans `bot/cogs`,
5. synchronise les slash commands.

## Base de données

La détection se fait dans `bot/database/engine.py` :

- `DATABASE_URL` vide → SQLite local avec `aiosqlite` ;
- `postgresql://...` ou `postgres://...` → conversion automatique en `postgresql+asyncpg://...` pour Railway ;
- `postgresql+asyncpg://...` → utilisé tel quel.

Les modèles de la Phase 1 couvrent toutes les tables prévues : membres, ordres, quêtes, contributions, trésorerie, tickets, déploiements, promotions, killboard, marché, snapshots fame, backups et santé bot.

## Déploiement Railway

Les fichiers nécessaires sont déjà présents :

- `Procfile` : `worker: python -m bot.main`
- `runtime.txt` : `3.11`
- `requirements.txt`

Variables Railway à prévoir :

```env
DISCORD_TOKEN=...
GUILD_ID=...
ALBION_GUILD_ID=...
DATABASE_URL=... # fourni par PostgreSQL Railway
```

Le code convertit automatiquement l'URL Railway PostgreSQL vers le driver asyncpg.

## Tester la Phase 1

Sans lancer Discord, vérifiez la syntaxe et la création de DB :

```bash
python -m compileall bot
python - <<'PY'
import asyncio
from bot.database.engine import init_db, dispose_engine, DATABASE_URL

async def main():
    print(DATABASE_URL)
    await init_db()
    await dispose_engine()

asyncio.run(main())
PY
```

Vous devez obtenir une base SQLite dans `data/` si `DATABASE_URL` est vide.

## Phases suivantes

- Phase 2 : onboarding + salon rôles
- Phase 3 : ordres prioritaires + quêtes
- Phase 4 : trésorerie + tickets
- Phase 5 : déploiement + promotion
- Phase 6 : marché + killboard
- Phase 7 : leaderboard + backup + admin + tâches finales
