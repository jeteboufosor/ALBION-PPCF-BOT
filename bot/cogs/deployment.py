"""Phase 5 — Déploiements / sorties de guilde."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.config import settings
from bot.database.crud import get_or_create_member
from bot.database.engine import session_scope
from bot.database.models import Deployment, DeploymentResponse, utcnow
from bot.utils.embeds import discord_timestamp, error_embed, success_embed, warning_embed
from bot.utils.helpers import parse_discord_time
from bot.utils.permissions import find_channel, find_role, is_officer

LOGGER = logging.getLogger(__name__)

ACTIVITY_TYPES = ("PvP", "ZvZ", "Donjon", "World Boss", "Gank", "Transport", "Autre")
CLASS_CHOICES = (("tank", "🛡️ Tank"), ("dps", "⚔️ DPS"), ("healer", "💚 Healer"), ("support", "🌿 Support"))
RESPONSE_LABELS = {"yes": "✅ PARTICIPANTS", "maybe": "⏳ PEUT-ÊTRE", "no": "❌ INDISPONIBLE"}


def _can_create(member: discord.Member) -> bool:
    return settings.test_mode or is_officer(member)


class ClassPickView(discord.ui.View):
    def __init__(self, deployment_id: int, response: str) -> None:
        super().__init__(timeout=60)
        self.deployment_id = deployment_id
        self.response = response
        for key, label in CLASS_CHOICES:
            self.add_item(ClassPickButton(key, label, deployment_id, response))


class ClassPickButton(discord.ui.Button["ClassPickView"]):
    def __init__(self, key: str, label: str, deployment_id: int, response: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.key = key
        self.deployment_id = deployment_id
        self.response = response

    async def callback(self, interaction: discord.Interaction) -> None:
        await save_response(interaction, self.deployment_id, self.response, self.key)


class DeployActionItem(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"deploy:(?P<action>yes|maybe|no):(?P<oid>[0-9]+)",
):
    def __init__(self, action: str, deployment_id: int) -> None:
        labels = {"yes": ("Je participe", "✅", discord.ButtonStyle.success), "maybe": ("Peut-être", "⏳", discord.ButtonStyle.primary), "no": ("Non", "❌", discord.ButtonStyle.danger)}
        label, emoji, style = labels[action]
        super().__init__(discord.ui.Button(label=label, emoji=emoji, style=style, custom_id=f"deploy:{action}:{deployment_id}"))
        self.action = action
        self.deployment_id = deployment_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /) -> DeployActionItem:
        return cls(match["action"], int(match["oid"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.action == "no":
            await interaction.response.defer(ephemeral=True)
            await save_response(interaction, self.deployment_id, "no", None)
            return
        await interaction.response.send_message("Choisis ton rôle :", view=ClassPickView(self.deployment_id, self.action), ephemeral=True)


class DeployButtons(discord.ui.View):
    def __init__(self, deployment_id: int) -> None:
        super().__init__(timeout=None)
        for action in ("yes", "maybe", "no"):
            self.add_item(DeployActionItem(action, deployment_id))


def build_deploy_embed(dep: Deployment) -> discord.Embed:
    yes, maybe, no = [], [], []
    for resp in dep.responses:
        name = resp.member.discord_name if resp.member else "?"
        mention = f"<@{resp.member.discord_id}>" if resp.member else name
        role = next((lab for key, lab in CLASS_CHOICES if key == resp.class_role), "")
        line = f"• {mention} {role}".strip()
        if resp.response == "yes":
            yes.append(line)
        elif resp.response == "maybe":
            maybe.append(line)
        else:
            no.append(line)
    slots = "illimité" if dep.max_slots is None else f"{len(yes)}/{dep.max_slots}"
    starts = dep.starts_at if dep.starts_at.tzinfo else dep.starts_at.replace(tzinfo=UTC)
    status = {"scheduled": "Prévu", "launched": "Lancé", "ended": "Terminé"}.get(dep.status, dep.status)
    embed = discord.Embed(
        description=(
            f"-# DÉPLOIEMENT\n"
            f"## 🐴  {dep.activity_type.upper()}\n\n"
            f"{dep.description}\n\n"
            f"**Stuff :** {dep.required_stuff or '—'}\n"
            f"**Départ :** {discord_timestamp(starts, 'F')} — {discord_timestamp(starts, 'R')}\n"
            f"**Places :** {slots}  ·  **Statut :** {status}"
        ),
        color=discord.Color.dark_green(),
    )
    embed.add_field(name=f"✅ Participants ({len(yes)})", value="\n".join(yes) or "*personne*", inline=False)
    embed.add_field(name=f"⏳ Peut-être ({len(maybe)})", value="\n".join(maybe) or "*personne*", inline=False)
    embed.add_field(name=f"❌ Indispo ({len(no)})", value="\n".join(no) or "*personne*", inline=False)
    embed.set_footer(text="Albion PPCF • Fort Sterling")
    return embed


async def _load_deploy(session, deployment_id: int) -> Deployment | None:
    result = await session.execute(
        select(Deployment)
        .options(selectinload(Deployment.responses).selectinload(DeploymentResponse.member))
        .where(Deployment.id == deployment_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def refresh_deploy(bot: commands.Bot, dep: Deployment) -> None:
    if not dep.channel_id or not dep.message_id:
        return
    channel = bot.get_channel(dep.channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        msg = await channel.fetch_message(dep.message_id)
        view = DeployButtons(dep.id) if dep.status == "scheduled" else None
        await msg.edit(embed=build_deploy_embed(dep), view=view)
    except discord.HTTPException:
        LOGGER.exception("Maj déploiement %s impossible", dep.id)


async def save_response(interaction: discord.Interaction, deployment_id: int, response: str, class_role: str | None) -> None:
    user = interaction.user
    async with session_scope() as session:
        dep = await _load_deploy(session, deployment_id)
        if dep is None or dep.status != "scheduled":
            msg = "Déploiement clos."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        if response == "yes" and dep.max_slots is not None:
            taken = sum(1 for r in dep.responses if r.response == "yes")
            already = any(r.member and r.member.discord_id == user.id and r.response == "yes" for r in dep.responses)
            if taken >= dep.max_slots and not already:
                text = "Plus de place."
                if interaction.response.is_done():
                    await interaction.followup.send(text, ephemeral=True)
                else:
                    await interaction.response.send_message(text, ephemeral=True)
                return
        member = await get_or_create_member(session, discord_id=user.id, discord_name=user.display_name)
        existing = next((r for r in dep.responses if r.member_id == member.id), None)
        if existing:
            existing.response = response
            existing.class_role = class_role
        else:
            session.add(DeploymentResponse(deployment_id=dep.id, member_id=member.id, response=response, class_role=class_role))
    async with session_scope() as session:
        dep = await _load_deploy(session, deployment_id)
        assert dep is not None
        await refresh_deploy(interaction.client, dep)
    text = "Réponse enregistrée."
    if not interaction.response.is_done():
        await interaction.response.send_message(text, ephemeral=True)
    else:
        await interaction.followup.send(text, ephemeral=True)


async def process_deployment_timers(bot: commands.Bot) -> None:
    now = utcnow()
    async with session_scope() as session:
        deps = list((await session.execute(select(Deployment).where(Deployment.status == "scheduled"))).scalars().all())
    for dep in deps:
        starts = dep.starts_at if dep.starts_at.tzinfo else dep.starts_at.replace(tzinfo=UTC)
        if dep.reminder_sent_at is None and now >= starts - timedelta(minutes=10) and now < starts:
            async with session_scope() as session:
                loaded = await _load_deploy(session, dep.id)
                if loaded is None:
                    continue
                loaded.reminder_sent_at = now
                people = [r for r in loaded.responses if r.response in {"yes", "maybe"} and r.member]
            for resp in people:
                user = bot.get_user(resp.member.discord_id)
                if user is None:
                    continue
                try:
                    await user.send(f"🐴 Déploiement **{dep.activity_type}** dans 10 min — {discord_timestamp(starts, 'R')}")
                except discord.HTTPException:
                    pass
        if now >= starts:
            async with session_scope() as session:
                loaded = await _load_deploy(session, dep.id)
                if loaded is None or loaded.status != "scheduled":
                    continue
                loaded.status = "launched"
                loaded.launched_at = now
            channel = bot.get_channel(dep.channel_id) if dep.channel_id else None
            if isinstance(channel, discord.TextChannel):
                await channel.send("🚀 Déploiement lancé !")
            async with session_scope() as session:
                loaded = await _load_deploy(session, dep.id)
                if loaded:
                    await refresh_deploy(bot, loaded)


class DeploymentCog(commands.Cog, name="Deployment"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(DeployActionItem)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(DeployActionItem)

    @app_commands.command(name="deployer", description="Crée un déploiement dans #déploiement.")
    @app_commands.guild_only()
    @app_commands.describe(heure="<t:1787511600:R>", places="Laisse vide = illimité")
    @app_commands.choices(type=[app_commands.Choice(name=t, value=t) for t in ACTIVITY_TYPES])
    async def deployer(
        self,
        interaction: discord.Interaction,
        type: app_commands.Choice[str],
        description: str,
        heure: str,
        stuff: str | None = None,
        places: int | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not _can_create(interaction.user):
            await interaction.followup.send("Officier+ (ou mode test).", ephemeral=True)
            return
        try:
            starts = parse_discord_time(heure)
        except ValueError as exc:
            await interaction.followup.send(embed=error_embed("Heure", str(exc)), ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        channel = find_channel(guild, "deployment")
        if channel is None:
            await interaction.followup.send(embed=error_embed("Salon #déploiement introuvable"), ephemeral=True)
            return
        ping = find_role(guild, "deployment")
        async with session_scope() as session:
            dep = Deployment(
                activity_type=type.value,
                description=description,
                required_stuff=stuff,
                starts_at=starts,
                max_slots=places if places and places > 0 else None,
                creator_discord_id=interaction.user.id,
            )
            session.add(dep)
            await session.flush()
            dep_id = dep.id
            loaded = await _load_deploy(session, dep_id)
            assert loaded is not None
            content = ping.mention if ping else None
            message = await channel.send(content=content, embed=build_deploy_embed(loaded), view=DeployButtons(dep_id))
            loaded.channel_id = channel.id
            loaded.message_id = message.id
        await interaction.followup.send(embed=success_embed("Déploiement posté", channel.mention), ephemeral=True)

    @app_commands.command(name="deployer_fin", description="Termine un déploiement (créateur uniquement).")
    @app_commands.guild_only()
    async def deployer_fin(self, interaction: discord.Interaction, id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        async with session_scope() as session:
            dep = await _load_deploy(session, id)
            if dep is None:
                await interaction.followup.send(embed=error_embed("Introuvable"), ephemeral=True)
                return
            if interaction.user.id != dep.creator_discord_id and not (isinstance(interaction.user, discord.Member) and _can_create(interaction.user)):
                await interaction.followup.send("Seul le créateur peut terminer.", ephemeral=True)
                return
            dep.status = "ended"
            dep.ended_at = utcnow()
        async with session_scope() as session:
            dep = await _load_deploy(session, id)
            if dep:
                await refresh_deploy(self.bot, dep)
        await interaction.followup.send(embed=success_embed("Déploiement terminé"), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DeploymentCog(bot))
