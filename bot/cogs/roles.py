"""Phase 2 — Salon #rôles : boutons toggle des rôles de classe."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import CLASS_ROLE_KEYS, ROLE_NAMES, settings
from bot.database.crud import get_or_create_member
from bot.database.engine import session_scope
from bot.utils.embeds import error_embed, info_embed, success_embed
from bot.utils.permissions import find_channel, find_role, is_guild_master, is_officer

LOGGER = logging.getLogger(__name__)

ROLE_BUTTONS: tuple[tuple[str, str, discord.ButtonStyle], ...] = (
    ("tank", "🛡️ Tank", discord.ButtonStyle.secondary),
    ("dps", "⚔️ DPS", discord.ButtonStyle.secondary),
    ("healer", "💚 Healer", discord.ButtonStyle.secondary),
    ("support", "🌿 Support", discord.ButtonStyle.secondary),
    ("lfg", "👥 Recherche-de-groupe", discord.ButtonStyle.primary),
    ("deployment", "🐺 Déploiement", discord.ButtonStyle.primary),
)


def _can_setup(member: discord.Member) -> bool:
    if settings.test_mode:
        return True
    return is_guild_master(member) or is_officer(member)


class ClassRoleButton(discord.ui.Button["ClassRolesView"]):
    def __init__(self, role_key: str, label: str, style: discord.ButtonStyle) -> None:
        super().__init__(label=label, style=style, custom_id=f"roles:toggle:{role_key}")
        self.role_key = role_key

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            await interaction.response.send_message("Utilise ce bouton sur le serveur.", ephemeral=True)
            return

        role = find_role(guild, self.role_key)
        pretty = ROLE_NAMES.get(self.role_key, self.role_key)
        if role is None:
            await interaction.response.send_message(
                embed=error_embed("Rôle introuvable", f"Le rôle **{pretty}** n'existe pas sur le serveur."),
                ephemeral=True,
            )
            return

        added = role not in user.roles
        try:
            if added:
                await user.add_roles(role, reason="Toggle rôle classe")
            else:
                await user.remove_roles(role, reason="Toggle rôle classe")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=error_embed("Permissions bot", "Le bot ne peut pas gérer ce rôle (place-le plus haut)."),
                ephemeral=True,
            )
            return

        async with session_scope() as session:
            member = await get_or_create_member(session, discord_id=user.id, discord_name=user.display_name)
            roles_state = dict(member.class_roles or {})
            roles_state[self.role_key] = added
            member.class_roles = roles_state

        prefix = "✅ Rôle ajouté" if added else "❌ Rôle retiré"
        await interaction.response.send_message(f"{prefix} : **{pretty}**", ephemeral=True)


class ClassRolesView(discord.ui.View):
    """Vue persistante des 6 boutons de rôles."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        for key, label, style in ROLE_BUTTONS:
            self.add_item(ClassRoleButton(key, label, style))


def build_roles_embed() -> discord.Embed:
    embed = info_embed(
        "🎭 Choisis tes rôles",
        "Clique pour **ajouter** ou **retirer** un rôle. Tu peux en cumuler autant que tu veux.",
    )
    embed.add_field(
        name="Classes",
        value="🛡️ Tank • ⚔️ DPS • 💚 Healer • 🌿 Support",
        inline=False,
    )
    embed.add_field(
        name="Notifications",
        value="👥 recherche-de-groupe • 🐺 déploiement",
        inline=False,
    )
    return embed


class Roles(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(ClassRolesView())

    @app_commands.command(name="setup_roles", description="Poste le panneau de rôles dans #rôles.")
    @app_commands.guild_only()
    async def setup_roles(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not _can_setup(interaction.user):
            await interaction.response.send_message("Permission insuffisante.", ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        channel = find_channel(guild, "roles")
        if channel is None:
            await interaction.response.send_message(
                embed=error_embed("Salon introuvable", "Impossible de trouver #rôles."),
                ephemeral=True,
            )
            return
        await channel.send(embed=build_roles_embed(), view=ClassRolesView())
        await interaction.response.send_message(
            embed=success_embed("Panneau rôles posté", channel.mention),
            ephemeral=True,
        )

    @app_commands.command(name="test_roles", description="[TEST] Affiche tes rôles de classe en base.")
    async def test_roles(self, interaction: discord.Interaction) -> None:
        async with session_scope() as session:
            member = await get_or_create_member(
                session, discord_id=interaction.user.id, discord_name=interaction.user.display_name
            )
            state = member.class_roles or {}
        lines = [f"• {ROLE_NAMES[k]} : {'✅' if state.get(k) else '❌'}" for k in CLASS_ROLE_KEYS]
        await interaction.response.send_message(
            embed=info_embed("Rôles enregistrés", "\n".join(lines) or "aucun"),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Roles(bot))
