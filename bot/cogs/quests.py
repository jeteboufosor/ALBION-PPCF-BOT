"""Phase 3 — Tableau des quêtes (mini-ordres, max 3 joueurs)."""

from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.database.crud import get_or_create_member
from bot.database.engine import session_scope
from bot.database.models import Quest, QuestParticipant, utcnow
from bot.utils.embeds import error_embed, info_embed, success_embed
from bot.utils.permissions import find_channel

LOGGER = logging.getLogger(__name__)


def build_quest_embed(quest: Quest) -> discord.Embed:
    names = [p.member.discord_name if p.member else "?" for p in quest.participants]
    status = "Terminée" if quest.status == "completed" else "Ouverte"
    embed = info_embed(f"📋 {quest.title}", quest.description)
    embed.add_field(name="Créateur", value=f"<@{quest.creator.discord_id}>" if quest.creator else "?", inline=True)
    embed.add_field(name="Statut", value=status, inline=True)
    embed.add_field(name="Récompense", value=quest.reward or "—", inline=False)
    embed.add_field(
        name=f"Participants ({len(names)}/3)",
        value="\n".join(f"• {n}" for n in names) or "Personne",
        inline=False,
    )
    return embed


class QuestButtons(discord.ui.View):
    def __init__(self, quest_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Participer", emoji="✅", style=discord.ButtonStyle.success, custom_id=f"quest:join:{quest_id}"))
        self.add_item(discord.ui.Button(label="Terminer", emoji="✔️", style=discord.ButtonStyle.secondary, custom_id=f"quest:done:{quest_id}"))


async def _load_quest(session, quest_id: int) -> Quest | None:
    result = await session.execute(
        select(Quest)
        .options(
            selectinload(Quest.creator),
            selectinload(Quest.participants).selectinload(QuestParticipant.member),
        )
        .where(Quest.id == quest_id)
    )
    return result.scalar_one_or_none()


async def refresh_quest(bot: commands.Bot, quest: Quest) -> None:
    if not quest.channel_id or not quest.message_id:
        return
    channel = bot.get_channel(quest.channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        message = await channel.fetch_message(quest.message_id)
        view = QuestButtons(quest.id) if quest.status == "active" else None
        await message.edit(embed=build_quest_embed(quest), view=view)
    except discord.HTTPException:
        LOGGER.exception("Maj quête %s impossible", quest.id)


class Quests(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="quete", description="Poste une quête (max 3 participants) dans #tableau-des-quêtes.")
    @app_commands.guild_only()
    async def quete(
        self,
        interaction: discord.Interaction,
        titre: str,
        description: str,
        recompense: str | None = None,
    ) -> None:
        guild = interaction.guild
        assert guild is not None
        channel = find_channel(guild, "quests")
        if channel is None:
            await interaction.response.send_message(embed=error_embed("Salon #tableau-des-quêtes introuvable"), ephemeral=True)
            return

        async with session_scope() as session:
            creator = await get_or_create_member(
                session, discord_id=interaction.user.id, discord_name=interaction.user.display_name
            )
            quest = Quest(
                title=titre,
                description=description,
                reward=recompense,
                creator_member_id=creator.id,
            )
            session.add(quest)
            await session.flush()
            loaded = await _load_quest(session, quest.id)
            assert loaded is not None
            message = await channel.send(embed=build_quest_embed(loaded), view=QuestButtons(quest.id))
            loaded.channel_id = channel.id
            loaded.message_id = message.id

        await interaction.response.send_message(
            embed=success_embed("Quête postée", channel.mention),
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type is not discord.InteractionType.component or not interaction.data:
            return
        custom_id = str(interaction.data.get("custom_id") or "")
        if not custom_id.startswith("quest:"):
            return
        _, action, raw = custom_id.split(":")
        quest_id = int(raw)
        async with session_scope() as session:
            quest = await _load_quest(session, quest_id)
            if quest is None:
                await interaction.response.send_message("Quête introuvable.", ephemeral=True)
                return
            member = await get_or_create_member(
                session, discord_id=interaction.user.id, discord_name=interaction.user.display_name
            )
            if action == "join":
                if quest.status != "active":
                    await interaction.response.send_message("Quête déjà terminée.", ephemeral=True)
                    return
                if any(p.member_id == member.id for p in quest.participants):
                    await interaction.response.send_message("Déjà inscrit.", ephemeral=True)
                    return
                if len(quest.participants) >= 3:
                    await interaction.response.send_message("Plus de place (max 3).", ephemeral=True)
                    return
                session.add(QuestParticipant(quest_id=quest.id, member_id=member.id))
                await session.flush()
                quest = await _load_quest(session, quest_id)
                assert quest is not None
                await refresh_quest(self.bot, quest)
                await interaction.response.send_message(embed=success_embed("Inscription OK"), ephemeral=True)
                return
            if action == "done":
                if quest.creator_member_id != member.id:
                    await interaction.response.send_message("Seul le créateur peut terminer.", ephemeral=True)
                    return
                quest.status = "completed"
                quest.completed_at = utcnow()
                quest.delete_after_at = utcnow() + timedelta(hours=6)
                await refresh_quest(self.bot, quest)
                await interaction.response.send_message(
                    embed=success_embed("Quête terminée", "Le message disparaîtra dans 6h."),
                    ephemeral=True,
                )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Quests(bot))
