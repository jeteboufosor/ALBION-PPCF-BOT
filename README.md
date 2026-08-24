# Albion PPCF Bot

Bot Discord (Python / discord.py / SQLAlchemy async) pour la guilde **PPCF** — Fort Sterling.

Déploiement : Railway + PostgreSQL. Processus : `python -m bot.main`.

## Variables Railway

```
DISCORD_TOKEN
GUILD_ID
ALBION_GUILD_ID
DATABASE_URL
TEST_MODE=true
SYNC_COMMANDS_ON_START=true
```

Passe `TEST_MODE=false` en prod (les `/test_*` et la plupart des setups restent officiers).

## Après chaque deploy

1. `/admin_sync`
2. Une fois : `/setup` puis les `/setup_*` (onboarding, rôles, trésorerie, déclaration, leaderboard)
3. Chaque membre : `/profil_pseudo` (killboard + fame auto)

Les dates se saisissent en timestamp Discord : `<t:1787511600:R>`.

Salon banque réel : `#💰 trésorie`. Rôle sorties : `🐴 déploiement`.

## Commandes

Tape `/aide` en jeu (boutons Membre / Ordres / Banque / Sorties / Staff).

### Membre
`/profil` `/profil_pseudo` `/profil_role` `/completer_profil` `/leaderboard`

### Marché (réponses publiques, watchlist privée)
`/prix` `/prix_comparer` `/black_market` `/historique_prix` `/craft_profit`  
`/watchlist` `/watchlist_ajouter` `/watchlist_supprimer`

### Ordres & quêtes
`/ordre_creer` `/ordre_info` `/quete`

Auto : fame PvE / gathering (API), silver (dépôt), item (apport ressource).  
Quota → réussi + points. Délai dépassé → échoué, 0 point.

### Banque
`/tresorerie_depot` `/tresorerie_retrait` `/dette_*` `/ressource_*`  
Donateur **obligatoire** sur dépôt et ressource.

### Sorties
`/deployer` `/deployer_fin` — rappels **DM uniquement** à T-10.  
`/promotion` `/retrograder`

### Staff
`/setup` `/setup_onboarding` `/setup_roles` `/setup_tresorerie` `/setup_declaration` `/setup_leaderboard`  
`/admin_statut` `/admin_sync` `/save` `/backup_info`  
`/test_alertes_prix` `/test_cleanup_ordres`

## Cron (Europe/Berlin)

| Quand | Quoi |
|---|---|
| 1 min | deadlines ordres, rappels déploiement |
| 5 min | killboard, fame ordres |
| 15 min | archive, watchlist prix |
| 04h00 | backup `#backup-sql` |
| 20h00 | rapport `#alertes-prix` |
| 1er 00h05 | reset scores mensuels |
| lundi 09h | santé `#alertes-bot` |
