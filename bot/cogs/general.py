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


class General(commands.Cog):
    """Commandes générales et diagnostic."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

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
