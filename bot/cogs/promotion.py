"""Phase 5 — Promotions de rang."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import ROLE_NAMES, settings
from bot.database.crud import get_or_create_member
from bot.database.engine import session_scope
from bot.database.models import Promotion
from bot.utils.embeds import error_embed, success_embed
from bot.utils.permissions import find_channel, find_role, is_guild_master, is_officer

RANKS = {
    "recruit": "🔵 Recrue",
    "knight": "🟣 Chevalier",
    "officer": "🟢 Officier",
    "war_lord": "🟡 Seigneur de Guerre",
    "grand_treasurer": "🔴 Grand Trésorier",
    "guild_master": "🟠 Maître de Guilde",
}

HIERARCHY = ("unverified", "recruit", "knight", "officer", "war_lord", "grand_treasurer", "guild_master")


def _can_promote(actor: discord.Member, new_rank: str) -> bool:
    if settings.test_mode or is_guild_master(actor):
        return True
    if is_officer(actor) and new_rank == "knight":
        return True
    return False


class PromotionCog(commands.Cog, name="Promotion"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="promotion", description="Promeut un membre vers un nouveau rang.")
    @app_commands.guild_only()
    @app_commands.choices(nouveau_rang=[app_commands.Choice(name=label, value=key) for key, label in RANKS.items()])
    async def promotion(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        nouveau_rang: app_commands.Choice[str],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not _can_promote(interaction.user, nouveau_rang.value):
            await interaction.followup.send(
                "Officier : Recrue → Chevalier. Maître de Guilde : tous les rangs.",
                ephemeral=True,
            )
            return
        guild = interaction.guild
        assert guild is not None
        new_role = find_role(guild, nouveau_rang.value)
        if new_role is None:
            await interaction.followup.send(embed=error_embed("Rôle Discord introuvable", RANKS[nouveau_rang.value]), ephemeral=True)
            return

        async with session_scope() as session:
            db = await get_or_create_member(session, discord_id=membre.id, discord_name=membre.display_name)
            old_key = db.current_rank
            db.current_rank = nouveau_rang.value
            session.add(
                Promotion(
                    member_id=db.id,
                    old_rank=old_key,
                    new_rank=nouveau_rang.value,
                    promoted_by_discord_id=interaction.user.id,
                )
            )

        old_role = find_role(guild, old_key) if old_key in ROLE_NAMES else None
        try:
            if old_role and old_role in membre.roles:
                await membre.remove_roles(old_role, reason="Promotion")
            if new_role not in membre.roles:
                await membre.add_roles(new_role, reason="Promotion")
        except discord.HTTPException:
            await interaction.followup.send(embed=error_embed("Le bot ne peut pas gérer ce rôle."), ephemeral=True)
            return

        old_label = RANKS.get(old_key, old_key)
        new_label = RANKS[nouveau_rang.value]
        embed = discord.Embed(
            description=(
                f"## 🎖️  PROMOTION\n\n"
                f"{membre.mention}\n"
                f"**{old_label}**  →  **{new_label}**\n\n"
                f"Promu par {interaction.user.mention}\nFélicitations ! 🎉"
            ),
            color=discord.Color.gold(),
        )
        channel = find_channel(guild, "promotion")
        if channel:
            await channel.send(embed=embed)
        try:
            await membre.send(embed=success_embed("Tu as été promu", f"{old_label} → {new_label}"))
        except discord.HTTPException:
            pass
        await interaction.followup.send(embed=success_embed("Promotion effectuée", new_label), ephemeral=True)

    @app_commands.command(name="retrograder", description="Rétrograde un membre vers un rang inférieur.")
    @app_commands.guild_only()
    @app_commands.choices(nouveau_rang=[app_commands.Choice(name=label, value=key) for key, label in RANKS.items()])
    async def retrograder(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        nouveau_rang: app_commands.Choice[str],
        raison: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not (
            settings.test_mode or is_guild_master(interaction.user)
        ):
            await interaction.followup.send("Maître de Guilde uniquement (ou mode test).", ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        new_role = find_role(guild, nouveau_rang.value)
        if new_role is None:
            await interaction.followup.send(embed=error_embed("Rôle Discord introuvable", RANKS[nouveau_rang.value]), ephemeral=True)
            return
        async with session_scope() as session:
            db = await get_or_create_member(session, discord_id=membre.id, discord_name=membre.display_name)
            old_key = db.current_rank
            db.current_rank = nouveau_rang.value
            session.add(
                Promotion(
                    member_id=db.id,
                    old_rank=old_key,
                    new_rank=nouveau_rang.value,
                    promoted_by_discord_id=interaction.user.id,
                    reason=raison,
                )
            )
        old_role = find_role(guild, old_key) if old_key in ROLE_NAMES else None
        try:
            if old_role and old_role in membre.roles:
                await membre.remove_roles(old_role, reason="Rétrogradation")
            if new_role not in membre.roles:
                await membre.add_roles(new_role, reason="Rétrogradation")
        except discord.HTTPException:
            await interaction.followup.send(embed=error_embed("Le bot ne peut pas gérer ce rôle."), ephemeral=True)
            return
        old_label = RANKS.get(old_key, old_key)
        new_label = RANKS[nouveau_rang.value]
        extra = f"\n{raison}" if raison else ""
        embed = discord.Embed(
            description=(
                f"## ⬇️  RÉTROGRADATION\n\n"
                f"{membre.mention}\n"
                f"**{old_label}**  →  **{new_label}**{extra}\n\n"
                f"Par {interaction.user.mention}"
            ),
            color=discord.Color.dark_grey(),
        )
        channel = find_channel(guild, "promotion")
        if channel:
            await channel.send(embed=embed)
        await interaction.followup.send(embed=success_embed("Rétrogradation effectuée", new_label), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PromotionCog(bot))
