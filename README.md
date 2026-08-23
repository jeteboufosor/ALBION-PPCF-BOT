# Albion PPCF Bot Discord

Bot Discord async pour une guilde Albion Online (Fort Sterling).

**Phase 2 — Onboarding + rôles** (Phase 1 déjà en place).

## Railway

Variables déjà prévues :

```env
DISCORD_TOKEN=...
GUILD_ID=...
ALBION_GUILD_ID=...
DATABASE_URL=...          # PostgreSQL Railway
TEST_MODE=true            # laisse true le temps des tests
SYNC_COMMANDS_ON_START=true
```

Passe `TEST_MODE=false` en production pour restreindre les commandes `/test_*` et les setups aux officiers.

## Commandes slash à tester

Après redéploiement, tape `/` dans Discord. Si rien n’apparaît, redémarre le worker Railway (sync au boot).

### Diagnostic
- `/ping` — latence
- `/setup` — rôles / salons manquants
- `/test_statut` — flags onboarding + TEST_MODE

### Setup des panneaux (une fois)
- `/setup_onboarding` — poste règles + guide + bouton ✅
- `/setup_roles` — poste les 6 boutons de classes dans #rôles

### Onboarding
- `/test_welcome` — simule ton arrivée (rôle Non vérifié + embed + bouton)
- `/test_reset_profil` — remet règles/profil à zéro
- `/test_validation` — force Recrue
- `/profil` `/profil_pseudo` `/profil_role`

### Rôles
- Clique les boutons du panneau #rôles (toggle)
- `/test_roles` — état enregistré en base

## Phase 3 — Ordres + quêtes

- `/ordre_creer` — titre, description, priorité, objectif, type, deadline `JJ/MM/AAAA HH:MM`, récompenses
- `/ordre_info numero:` — fiche d'un ordre
- `/quete` — mini-ordre max 3 dans #tableau-des-quêtes
- `/test_cleanup_ordres` — force l'archivage (24h / 6h)

Boutons ordre : Accepter / Progression (gestionnaires) / Terminer / Annuler.  
En `TEST_MODE=true` tout le monde peut créer/terminer.

## Parcours de test recommandé

1. `/setup` → corrige les noms de rôles/salons s’ils sont listés manquants
2. `/setup_onboarding` puis `/setup_roles`
3. `/test_reset_profil`
4. Accepte les règles + complète le profil (ou `/test_welcome` puis le formulaire)
5. Vérifie #arrivé-départ et le passage **Non vérifié → Recrue**
6. Toggle Tank / DPS / etc. puis `/test_roles`

Le bot doit pouvoir **gérer les rôles** (rôle bot au-dessus de Recrue / Non vérifié / classes).
