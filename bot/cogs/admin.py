"""Phase 7 — Commandes admin."""

from __future__ import annotations

from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import settings
from bot.database.engine import IS_POSTGRES
from bot.utils.embeds import info_embed
from bot.utils.permissions import is_guild_master, is_officer


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="admin_statut", description="Santé du bot.")
    @app_commands.guild_only()
    async def admin_statut(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not (settings.test_mode or is_officer(interaction.user)):
            await interaction.response.send_message("Officier+.", ephemeral=True)
            return
        started = getattr(self.bot, "started_at", datetime.now(UTC))
        uptime = datetime.now(UTC) - started
        hours = int(uptime.total_seconds() // 3600)
        mins = int((uptime.total_seconds() % 3600) // 60)
        await interaction.response.send_message(
            embed=info_embed(
                "🛠️ Statut bot",
                f"Uptime : **{hours}h {mins}min**\n"
                f"TEST_MODE : **{settings.test_mode}**\n"
                f"DB : **{'PostgreSQL' if IS_POSTGRES else 'SQLite'}**\n"
                f"Guildes : **{len(self.bot.guilds)}**\n"
                f"Latence : **{round(self.bot.latency*1000)} ms**",
            ),
            ephemeral=True,
        )

    @app_commands.command(name="admin_sync", description="Resynchronise les slash commands.")
    @app_commands.guild_only()
    async def admin_sync(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not (settings.test_mode or is_guild_master(interaction.user)):
            await interaction.response.send_message("Maître de Guilde.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        if settings.guild_id:
            guild = discord.Object(id=settings.guild_id)
            self.bot.tree.copy_global_to(guild=guild)
            synced = await self.bot.tree.sync(guild=guild)
        else:
            synced = await self.bot.tree.sync()
        await interaction.followup.send(f"{len(synced)} commande(s) sync.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
