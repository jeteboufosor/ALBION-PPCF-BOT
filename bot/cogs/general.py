"""Cog général: premières slash commands du bot.

Fournit /ping (diagnostic rapide) et /setup (vérification de la configuration
du serveur: rôles et salons attendus). Sans au moins un cog exposant des
commandes, la synchronisation ne publie rien sur Discord.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import CHANNEL_NAMES, ROLE_NAMES, settings

HELP_PAGES: dict[str, tuple[str, str]] = {
    "membre": (
        "👤 Membre",
        "**Profil**\n"
        "`/profil` `/profil_pseudo` `/profil_role` `/completer_profil`\n"
        "`/aide` — ce menu\n\n"
        "**Marché** (public)\n"
        "`/prix` `/prix_comparer` `/black_market` `/historique_prix` `/craft_profit`\n"
        "`/watchlist` `/watchlist_ajouter` `/watchlist_supprimer`\n\n"
        "**Classement**\n"
        "`/leaderboard` — 1 embed, boutons catégorie + ⏳ période",
    ),
    "ordres": (
        "🎯 Ordres",
        "`/ordre_creer` — deadline en `<t:unix:R>`\n"
        "`/ordre_info`\n"
        "`/quete` — max 3 dans #tableau-des-quêtes\n\n"
        "Types auto : fame PvE / gathering (besoin `/profil_pseudo`), "
        "silver (dépôt trésorerie), item (apport ressource).\n"
        "Quota → **réussi** + points. Délai dépassé → **échoué**, 0 point.",
    ),
    "banque": (
        "💰 Banque",
        "`/setup_tresorerie` `/tresorerie_depot` `/tresorerie_retrait`\n"
        "`/dette_ajouter` `/dette_rembourser`\n"
        "`/ressource_ajouter` `/ressource_supprimer`\n"
        "`/setup_declaration` — Don / Ordre / Craft / Problème / Autre\n\n"
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
        "`/setup` `/setup_onboarding` `/setup_roles` `/setup_leaderboard`\n"
        "`/admin_statut` `/admin_sync` `/save` `/backup_info`\n"
        "`/test_alertes_prix` `/test_cleanup_ordres`\n\n"
        "Cron : backup 04h · prix 20h · reset 1er · santé lundi 09h.",
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

    @app_commands.command(
        name="setup",
        description="Vérifie la configuration du serveur (rôles et salons attendus).",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def setup_check(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Cette commande doit être utilisée dans un serveur.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        existing_roles = {role.name for role in guild.roles}
        existing_channels = {channel.name for channel in guild.channels}

        missing_roles = [name for name in ROLE_NAMES.values() if name not in existing_roles]
        from bot.utils.permissions import find_channel

        missing_channels = []
        found_channels = []
        for key, name in CHANNEL_NAMES.items():
            ch = find_channel(guild, key)
            if ch is None:
                missing_channels.append(name)
            else:
                found_channels.append(f"✅ {ch.mention}")

        embed = discord.Embed(
            title="🛠️ Vérification de la configuration",
            color=discord.Color.green() if not (missing_roles or missing_channels) else discord.Color.orange(),
        )
        embed.add_field(
            name=f"Rôles ({len(ROLE_NAMES) - len(missing_roles)}/{len(ROLE_NAMES)})",
            value="✅ Tous présents" if not missing_roles else "\n".join(f"❌ {name}" for name in missing_roles[:15]),
            inline=False,
        )
        embed.add_field(
            name=f"Salons ({len(CHANNEL_NAMES) - len(missing_channels)}/{len(CHANNEL_NAMES)})",
            value="✅ Tous présents" if not missing_channels else "\n".join(f"❌ {name}" for name in missing_channels[:15]),
            inline=False,
        )
        embed.add_field(
            name="Configuration bot",
            value=(
                f"GUILD_ID: `{settings.guild_id or 'non défini'}`\n"
                f"Base de données: `{'PostgreSQL' if settings.database_url else 'SQLite'}`\n"
                f"Mode test: `{settings.test_mode}`\n"
                f"Sync au démarrage: `{settings.sync_commands_on_start}`"
            ),
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
