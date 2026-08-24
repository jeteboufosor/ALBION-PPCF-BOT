# Albion PPCF Bot

Bot Discord (Python / discord.py / SQLAlchemy async) pour la guilde **PPCF** — Fort Sterling.

Déploiement : Railway + PostgreSQL. Processus : `python -m bot.main`.

## Variables Railway

```
DISCORD_TOKEN
GUILD_ID
ALBION_GUILD_ID
DATABASE_URL
TEST_MODE=false
SYNC_COMMANDS_ON_START=true
RESET_DATABASE=true
```

`RESET_DATABASE=true` **une seule fois** au premier deploy de lancement (wipe total). **Supprime la variable juste après** sinon chaque redémarrage vide la base.

**Ne définis pas** `ALBION_API_BASE_URL` / `ALBION_MARKET_BASE_URL` sauf pour forcer autre chose que l’Europe.

## API Albion — Europe uniquement

| Usage | URL |
|---|---|
| Gameinfo (joueurs, fame, kills, guilde) | `https://gameinfo-ams.albiononline.com/api/gameinfo` |
| Recherche joueur | `…/search?q=PSEUDO` |
| Joueur | `…/players/{id}` |
| Stats fame | `…/players/{id}/statistics` |
| Kills / morts | `…/players/{id}/kills` · `…/deaths` |
| Membres de guilde | `…/guilds/{ALBION_GUILD_ID}/members` |
| Killboard events | `…/events?limit=50` |
| Marché (prix / histo) | `https://europe.albion-online-data.com/api/v2/stats` |
| Prix | `…/prices/{ITEM_ID}?locations=Fort Sterling` |
| Historique | `…/history/{ITEM_ID}?locations=Fort Sterling&time-scale=24` |
| Icônes items | `https://render.albiononline.com/v1/item/{ITEM_ID}.png` |
| Portrait équipé | `https://render.albiononline.com/v1/character/{slots}.png?size=512` |
| Catalogue items FR | `https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.json` |
| Craft (lien) | `https://albion.tools/crafting?item={ITEM_ID}` |

Amérique (à **ne pas** utiliser) : `gameinfo.albiononline.com` · `west.albion-online-data.com`  
Asie : `gameinfo-sgp.albiononline.com` · `east.albion-online-data.com`

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
