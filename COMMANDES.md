# Inventaire des commandes PPCF

En `TEST_MODE=true` (Railway par défaut), presque tout est ouvert. En prod (`false`), les colonnes **Qui** s’appliquent.

| Commande | Qui | Cible / notes |
|---|---|---|
| `/aide` | tout le monde | — |
| `/ping` | tout le monde | — |
| `/profil` | tout le monde | option `membre` = fiche de quelqu’un d’autre |
| `/profil_pseudo` | tout le monde | soi |
| `/profil_role` | tout le monde | soi (donne le rôle PVP/PVE/…) |
| `/completer_profil` | tout le monde | soi |
| `/leaderboard` | tout le monde | — |
| `/prix` `/prix_comparer` `/black_market` `/historique_prix` `/craft_profit` | tout le monde | public |
| `/watchlist` `/watchlist_ajouter` `/watchlist_supprimer` | tout le monde | tes alertes (privé) |
| `/ordre_info` | tout le monde | numéro d’ordre |
| `/quete` | tout le monde | — |
| `/ordre_creer` | SdG / Grand Trésorier | — |
| `/tresorerie_depot` | Grand Trésorier | **donateur** obligatoire |
| `/taxe` | Grand Trésorier | montant uniquement — collecte hebdo, effort collectif, pas de classement ; crédite la progression des ordres « Silver donné » actifs |
| `/tresorerie_retrait` | Grand Trésorier | — |
| `/dette_ajouter` | Grand Trésorier | **membre** |
| `/dette_rembourser` | Grand Trésorier | id dette |
| `/ressource_ajouter` | Grand Trésorier | **demandeur** |
| `/ressource_supprimer` | Grand Trésorier | **donateur** obligatoire |
| `/deployer` | Officier+ | — |
| `/deployer_fin` | créateur ou Officier+ | id déploiement |
| `/promotion` | Officier → Chevalier seulement ; MdG = tous | **membre** |
| `/retrograder` | Maître de Guilde | **membre** |
| `/setup` | admin Discord | — |
| `/setup_onboarding` | Officier+ | règles + **guide** + arrivée |
| `/setup_roles` | Officier+ | crée les rôles manquants |
| `/setup_tresorerie` | Grand Trésorier | — |
| `/setup_declaration` | Officier+ | — |
| `/setup_leaderboard` | tout le monde (TEST) / staff | — |
| `/admin_statut` | Officier+ | — |
| `/admin_sync` | Maître de Guilde | — |
| `/save` `/backup_info` `/load` | Maître de Guilde | — |
| `/test_*` | TEST_MODE ou Officier | soi |

Boutons : Accepter/Progression/Terminer (ordres), Participer/Terminer (quêtes), RSVP déploiement, tickets #declaration, rôles #rôles.
