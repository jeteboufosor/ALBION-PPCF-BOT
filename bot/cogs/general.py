"""Cog général: premières slash commands du bot.

Fournit /ping (diagnostic rapide) et /setup (vérification de la configuration
du serveur: rôles et salons attendus). Sans au moins un cog exposant des
commandes, la synchronisation ne publie rien sur Discord.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

HELP_PAGES: dict[str, tuple[str, str]] = {
    "membre": (
        "👤 Membre",
        "**Profil**\n"
        "`/profil` `/completer_profil` `/aide`\n\n"
        "**Marché** (public)\n"
        "`/prix` `/prix_comparer` `/black_market` `/historique_prix` `/craft_profit`\n"
        "`/watchlist` `/watchlist_ajouter` `/watchlist_supprimer`\n\n"
        "**Classement** — salon #🏆 leaderboard (boutons)",
    ),
    "ordres": (
        "🎯 Ordres",
        "`/ordre_creer` — deadline en `<t:unix:R>`\n"
        "`/ordre_info`\n"
        "`/quete` — max 3 dans #tableau-des-quêtes\n\n"
        "Types auto : fame PvE / gathering (pseudo dans le formulaire), "
        "silver (dépôt trésorerie), item (apport ressource).\n"
        "Quota → **réussi** + points. Délai dépassé → **échoué**, 0 point.",
    ),
    "banque": (
        "💰 Banque",
        "`/tresorerie_depot` `/tresorerie_retrait`\n"
        "`/dette_ajouter` `/dette_rembourser`\n"
        "`/ressource_ajouter` `/ressource_supprimer`\n"
        "Tickets : Don / Ordre / Craft / Problème / Autre dans #✉️ declaration\n\n"
        "Salon réel : `#💰 trésorie`. Donateur **obligatoire** sur dépôt et ressource.",
    ),
    "sortie": (
        "🐴 Sorties",
        "`/deployer` — heure `<t:unix:R>`, places optionnelles\n"
        "`/deployer_fin`\n"
        "`/promotion` `/retrograder`\n\n"
        "Rappels **DM uniquement** (yes/maybe) à T-10 min.",
    ),
    "staff": (
        "🛠️ Staff",
        "`/admin_statut` `/admin_sync` `/save` `/backup_info`\n\n"
        "Cron : backup 04h · prix 20h · reset 1er · santé lundi 09h.",
    ),
    "droits": (
        "📜 Droits",
        "**Tout le monde** — `/aide` `/ping` `/profil` `/completer_profil` "
        "`/prix*` `/watchlist*` `/ordre_info` `/quete`\n\n"
        "**Officier+** — `/deployer` `/deployer_fin` `/promotion` (officier : Chevalier) `/admin_statut`\n\n"
        "**Seigneur de Guerre / Grand Trésorier** — `/ordre_creer` + boutons Progression/Terminer\n\n"
        "**Grand Trésorier** — `/tresorerie_*` `/dette_*` `/ressource_*` "
        "(donateur **obligatoire** sur dépôt et ressource)\n\n"
        "**Maître de Guilde** — `/retrograder` `/admin_sync` `/save` `/load` `/backup_info`\n\n"
        "Cible : `/profil membre:` n'importe qui · dépôt/ressource = **donateur** · "
        "promo/rétro = **membre** choisi.",
    ),
}


def build_help_embed(page: str = "membre") -> discord.Embed:
    if page not in HELP_PAGES:
        page = "membre"
    title, body = HELP_PAGES[page]
    embed = discord.Embed(
        description=f"-# AIDE PPCF\n## {title}\n\n{body}",
        color=discord.Color.orange(),
    )
    embed.set_footer(text="Albion PPCF • Fort Sterling")
    return embed


class HelpButton(discord.ui.Button["HelpView"]):
    def __init__(self, page: str, current: str) -> None:
        title = HELP_PAGES[page][0]
        emoji, label = title.split(" ", 1)
        super().__init__(
            label=label,
            emoji=emoji,
            style=discord.ButtonStyle.primary if page == current else discord.ButtonStyle.secondary,
            custom_id=f"help:{page}",
        )
        self.page = page

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=build_help_embed(self.page), view=HelpView(self.page))


class HelpView(discord.ui.View):
    def __init__(self, current: str = "membre") -> None:
        super().__init__(timeout=None)
        for key in HELP_PAGES:
            self.add_item(HelpButton(key, current))


class General(commands.Cog):
    """Commandes générales et diagnostic."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(HelpView())

    @app_commands.command(name="aide", description="Guide des commandes (boutons de catégories).")
    async def aide(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=build_help_embed("membre"), view=HelpView("membre"), ephemeral=True)

    @app_commands.command(name="ping", description="Vérifie que le bot répond et affiche sa latence.")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong ! Latence: **{latency_ms} ms**", ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
