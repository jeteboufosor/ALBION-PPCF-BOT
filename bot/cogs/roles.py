"""Phase 2 — Salon #rôles : style de jeu + classes + pings."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import CLASS_ROLE_KEYS, PLAYSTYLE_ROLE_KEYS, ROLE_NAMES, settings
from bot.database.crud import get_or_create_member
from bot.database.engine import session_scope
from bot.utils.embeds import error_embed, info_embed, success_embed
from bot.utils.permissions import find_channel, find_role, is_guild_master, is_officer, role_by_name

LOGGER = logging.getLogger(__name__)

ROLE_BUTTONS: tuple[tuple[str, str, discord.ButtonStyle], ...] = (
    ("pvp", "⚔️ PVP", discord.ButtonStyle.secondary),
    ("pve", "🛡️ PVE", discord.ButtonStyle.secondary),
    ("gathering", "⛏️ Gathering", discord.ButtonStyle.secondary),
    ("craft", "🔨 Craft / Éco", discord.ButtonStyle.secondary),
    ("polyvalent", "🎲 Polyvalent", discord.ButtonStyle.secondary),
    ("tank", "🛡️ Tank", discord.ButtonStyle.primary),
    ("dps", "⚔️ DPS", discord.ButtonStyle.primary),
    ("healer", "💚 Healer", discord.ButtonStyle.primary),
    ("support", "🌿 Support", discord.ButtonStyle.primary),
    ("lfg", "👥 LFG", discord.ButtonStyle.success),
    ("deployment", "🐴 Déploiement", discord.ButtonStyle.success),
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
                embed=error_embed("Rôle introuvable", f"Le rôle **{pretty}** n'existe pas. Relance `/setup_roles`."),
                ephemeral=True,
            )
            return

        exclusive = self.role_key in PLAYSTYLE_ROLE_KEYS
        added = role not in user.roles
        try:
            if exclusive and added:
                extras = []
                for other in PLAYSTYLE_ROLE_KEYS:
                    if other == self.role_key:
                        continue
                    other_role = find_role(guild, other)
                    if other_role and other_role in user.roles:
                        extras.append(other_role)
                if extras:
                    await user.remove_roles(*extras, reason="Un seul style de jeu")
                await user.add_roles(role, reason="Style de jeu")
            elif added:
                await user.add_roles(role, reason="Toggle rôle")
            else:
                await user.remove_roles(role, reason="Toggle rôle")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=error_embed("Permissions bot", "Le bot ne peut pas gérer ce rôle (place-le plus haut)."),
                ephemeral=True,
            )
            return

        async with session_scope() as session:
            member = await get_or_create_member(session, discord_id=user.id, discord_name=user.display_name)
            roles_state = dict(member.class_roles or {})
            if exclusive and added:
                for other in PLAYSTYLE_ROLE_KEYS:
                    roles_state[other] = other == self.role_key
                member.preferred_gameplay = self.role_key
            else:
                roles_state[self.role_key] = added
            member.class_roles = roles_state

        prefix = "✅ Rôle ajouté" if added else "❌ Rôle retiré"
        await interaction.response.send_message(f"{prefix} : **{pretty}**", ephemeral=True)


class ClassRolesView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        for key, label, style in ROLE_BUTTONS:
            self.add_item(ClassRoleButton(key, label, style))


def build_roles_embed() -> discord.Embed:
    embed = discord.Embed(
        description=(
            "-# RÔLES\n"
            "## 🎭  CHOISIS TES RÔLES\n\n"
            "Clique pour **ajouter** ou **retirer**. "
            "Le **style de jeu** est unique (un seul à la fois).\n\n"
            "**Style** (1 seul)\n"
            "⚔️ PVP   ·   🛡️ PVE   ·   ⛏️ Gathering\n"
            "🔨 Craft / Économie   ·   🎲 Polyvalent\n\n"
            "**Classe** (cumulables)\n"
            "🛡️ Tank   ·   ⚔️ DPS   ·   💚 Healer   ·   🌿 Support\n\n"
            "**Pings**\n"
            "👥 LFG   ·   🐴 Déploiement"
        ),
        color=discord.Color.purple(),
    )
    embed.set_footer(text="Albion PPCF • Fort Sterling")
    return embed


async def ensure_toggle_roles(guild: discord.Guild) -> list[str]:
    created: list[str] = []
    for key in (*PLAYSTYLE_ROLE_KEYS, "tank", "dps", "healer", "support", "lfg", "deployment"):
        name = ROLE_NAMES[key]
        if role_by_name(guild, name) is None:
            try:
                await guild.create_role(name=name, mentionable=True, reason="setup_roles")
                created.append(name)
            except discord.HTTPException:
                LOGGER.warning("Création rôle %s impossible", name)
    return created


class Roles(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(ClassRolesView())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Roles(bot))
