"""Phase 4 — Trésorerie, dettes, demandes de ressources."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.config import settings
from bot.database.crud import get_or_create_member, get_treasury_state
from bot.database.engine import session_scope
from bot.database.models import Debt, ResourceRequest, TreasuryTransaction, utcnow
from bot.utils.embeds import discord_timestamp, error_embed, format_silver, info_embed, success_embed, warning_embed
from bot.utils.permissions import can_manage_treasury, find_channel

LOGGER = logging.getLogger(__name__)
TZ = ZoneInfo("Europe/Berlin")


def _can_tresorerie(member: discord.Member) -> bool:
    return settings.test_mode or can_manage_treasury(member)


def _parse_date(raw: str) -> datetime:
    text = raw.strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%Y %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt == "%d/%m/%Y" or fmt == "%Y-%m-%d":
                dt = dt.replace(hour=23, minute=59)
            return dt.replace(tzinfo=TZ)
        except ValueError:
            continue
    raise ValueError("Date : JJ/MM/AAAA")


async def build_treasury_embed():
    async with session_scope() as session:
        state = await get_treasury_state(session)
        debts = list(
            (
                await session.execute(
                    select(Debt).options(selectinload(Debt.member)).where(Debt.status == "open").order_by(Debt.deadline_at)
                )
            ).scalars().all()
        )
        resources = list(
            (await session.execute(select(ResourceRequest).where(ResourceRequest.status == "open"))).scalars().all()
        )
        balance = state.current_balance
        deposited = state.total_deposited
        withdrawn = state.total_withdrawn

    embed = discord.Embed(
        title="💰  TRÉSORERIE DE GUILDE",
        description=(
            f"# {format_silver(balance)}\n"
            f"-# Solde actuel\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(name="📥 Total donné", value=format_silver(deposited), inline=True)
    embed.add_field(name="📤 Total retiré", value=format_silver(withdrawn), inline=True)
    debt_lines = []
    for debt in debts[:10]:
        name = debt.member.discord_name if debt.member else "?"
        debt_lines.append(f"• {name} — {format_silver(debt.remaining_amount)} (id `{debt.id}` · {discord_timestamp(debt.deadline_at, 'R')})")
    embed.add_field(name="📋 Dettes en cours", value="\n".join(debt_lines) or "*Aucune*", inline=False)
    res_lines = [f"• {r.quantity}× {r.item_name} (id `{r.id}`)" for r in resources[:10]]
    embed.add_field(name="📥 Demandes de ressources", value="\n".join(res_lines) or "*Aucune*", inline=False)
    embed.set_footer(text="Albion PPCF • Fort Sterling")
    return embed


async def refresh_treasury_panel(bot: commands.Bot, guild: discord.Guild) -> None:
    channel = find_channel(guild, "treasury")
    if channel is None:
        return
    embed = await build_treasury_embed()
    async with session_scope() as session:
        state = await get_treasury_state(session)
        msg_id = state.treasury_message_id
    if msg_id:
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(embed=embed)
            return
        except discord.HTTPException:
            pass
    sent = await channel.send(embed=embed)
    async with session_scope() as session:
        state = await get_treasury_state(session)
        state.treasury_message_id = sent.id


async def log_history(guild: discord.Guild, title: str, description: str) -> None:
    channel = find_channel(guild, "history")
    if channel is None:
        return
    await channel.send(embed=info_embed(title, description))


class Treasury(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="setup_tresorerie", description="Poste / rafraîchit le panneau #trésorerie.")
    @app_commands.guild_only()
    async def setup_tresorerie(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not _can_tresorerie(interaction.user):
            await interaction.response.send_message("Permission insuffisante.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await refresh_treasury_panel(self.bot, interaction.guild)
        await interaction.followup.send(embed=success_embed("Panneau trésorerie à jour"), ephemeral=True)

    @app_commands.command(name="tresorerie_depot", description="Dépose du silver en trésorerie.")
    @app_commands.guild_only()
    async def tresorerie_depot(self, interaction: discord.Interaction, montant: int, note: str) -> None:
        if not isinstance(interaction.user, discord.Member) or not _can_tresorerie(interaction.user):
            await interaction.response.send_message("Grand Trésorier uniquement (ou mode test).", ephemeral=True)
            return
        if montant <= 0:
            await interaction.response.send_message(embed=error_embed("Montant invalide"), ephemeral=True)
            return
        async with session_scope() as session:
            state = await get_treasury_state(session)
            state.current_balance += montant
            state.total_deposited += montant
            session.add(
                TreasuryTransaction(
                    transaction_type="deposit",
                    amount=montant,
                    balance_after=state.current_balance,
                    note=note,
                    author_discord_id=interaction.user.id,
                )
            )
        await refresh_treasury_panel(self.bot, interaction.guild)
        await log_history(
            interaction.guild,
            "📥 Dépôt",
            f"{interaction.user.mention} +{format_silver(montant)}\n{note}",
        )
        await interaction.response.send_message(embed=success_embed("Dépôt enregistré", format_silver(montant)), ephemeral=True)

    @app_commands.command(name="tresorerie_retrait", description="Retire du silver de la trésorerie.")
    @app_commands.guild_only()
    async def tresorerie_retrait(self, interaction: discord.Interaction, montant: int, note: str) -> None:
        if not isinstance(interaction.user, discord.Member) or not _can_tresorerie(interaction.user):
            await interaction.response.send_message("Grand Trésorier uniquement (ou mode test).", ephemeral=True)
            return
        if montant <= 0:
            await interaction.response.send_message(embed=error_embed("Montant invalide"), ephemeral=True)
            return
        async with session_scope() as session:
            state = await get_treasury_state(session)
            if state.current_balance < montant:
                await interaction.response.send_message(embed=error_embed("Solde insuffisant", format_silver(state.current_balance)), ephemeral=True)
                return
            state.current_balance -= montant
            state.total_withdrawn += montant
            session.add(
                TreasuryTransaction(
                    transaction_type="withdraw",
                    amount=montant,
                    balance_after=state.current_balance,
                    note=note,
                    author_discord_id=interaction.user.id,
                )
            )
        await refresh_treasury_panel(self.bot, interaction.guild)
        await log_history(interaction.guild, "📤 Retrait", f"{interaction.user.mention} -{format_silver(montant)}\n{note}")
        await interaction.response.send_message(embed=success_embed("Retrait enregistré", format_silver(montant)), ephemeral=True)

    @app_commands.command(name="dette_ajouter", description="Ajoute une dette à un membre.")
    @app_commands.guild_only()
    async def dette_ajouter(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        montant: int,
        deadline: str,
        raison: str,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not _can_tresorerie(interaction.user):
            await interaction.response.send_message("Permission insuffisante.", ephemeral=True)
            return
        try:
            ends = _parse_date(deadline)
        except ValueError as exc:
            await interaction.response.send_message(embed=error_embed("Deadline", str(exc)), ephemeral=True)
            return
        async with session_scope() as session:
            db_member = await get_or_create_member(session, discord_id=membre.id, discord_name=membre.display_name)
            debt = Debt(
                member_id=db_member.id,
                amount=montant,
                remaining_amount=montant,
                deadline_at=ends,
                reason=raison,
                created_by_discord_id=interaction.user.id,
            )
            session.add(debt)
            await session.flush()
            debt_id = debt.id
        await refresh_treasury_panel(self.bot, interaction.guild)
        await log_history(
            interaction.guild,
            "📋 Dette ajoutée",
            f"{membre.mention} — {format_silver(montant)}\nÉchéance {discord_timestamp(ends, 'F')}\n{raison}\nid `{debt_id}`",
        )
        await interaction.response.send_message(embed=success_embed("Dette créée", f"id `{debt_id}`"), ephemeral=True)

    @app_commands.command(name="dette_rembourser", description="Marque une dette comme remboursée.")
    @app_commands.guild_only()
    async def dette_rembourser(self, interaction: discord.Interaction, id: int) -> None:
        if not isinstance(interaction.user, discord.Member) or not _can_tresorerie(interaction.user):
            await interaction.response.send_message("Permission insuffisante.", ephemeral=True)
            return
        async with session_scope() as session:
            debt = await session.get(Debt, id)
            if debt is None or debt.status != "open":
                await interaction.response.send_message(embed=error_embed("Dette introuvable"), ephemeral=True)
                return
            debt.status = "repaid"
            debt.remaining_amount = 0
            debt.repaid_at = utcnow()
        await refresh_treasury_panel(self.bot, interaction.guild)
        await log_history(interaction.guild, "✅ Dette remboursée", f"id `{id}` par {interaction.user.mention}")
        await interaction.response.send_message(embed=success_embed("Dette soldée"), ephemeral=True)

    @app_commands.command(name="ressource_ajouter", description="Ajoute une demande de ressource visible en trésorerie.")
    @app_commands.guild_only()
    async def ressource_ajouter(
        self,
        interaction: discord.Interaction,
        item: str,
        quantite: int,
        demandeur: discord.Member,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not _can_tresorerie(interaction.user):
            await interaction.response.send_message("Permission insuffisante.", ephemeral=True)
            return
        async with session_scope() as session:
            db_member = await get_or_create_member(session, discord_id=demandeur.id, discord_name=demandeur.display_name)
            req = ResourceRequest(
                item_name=item,
                quantity=quantite,
                requester_member_id=db_member.id,
                created_by_discord_id=interaction.user.id,
            )
            session.add(req)
            await session.flush()
            rid = req.id
        await refresh_treasury_panel(self.bot, interaction.guild)
        await log_history(interaction.guild, "📦 Demande ressource", f"{quantite}× {item} pour {demandeur.mention} (id `{rid}`)")
        await interaction.response.send_message(embed=success_embed("Demande ajoutée", f"id `{rid}`"), ephemeral=True)

    @app_commands.command(name="ressource_supprimer", description="Retire une demande de ressource.")
    @app_commands.guild_only()
    async def ressource_supprimer(self, interaction: discord.Interaction, id: int) -> None:
        if not isinstance(interaction.user, discord.Member) or not _can_tresorerie(interaction.user):
            await interaction.response.send_message("Permission insuffisante.", ephemeral=True)
            return
        async with session_scope() as session:
            req = await session.get(ResourceRequest, id)
            if req is None:
                await interaction.response.send_message(embed=error_embed("Introuvable"), ephemeral=True)
                return
            req.status = "closed"
            req.fulfilled_at = utcnow()
        await refresh_treasury_panel(self.bot, interaction.guild)
        await interaction.response.send_message(embed=warning_embed("Demande retirée"), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Treasury(bot))
