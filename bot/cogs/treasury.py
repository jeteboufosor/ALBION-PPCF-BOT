"""Phase 4 — Trésorerie, dettes, demandes de ressources."""

from __future__ import annotations

import logging
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.config import settings
from bot.database.crud import get_or_create_member, get_treasury_state
from bot.database.engine import session_scope
from bot.database.models import ContributionScore, Debt, GuildDonation, ResourceRequest, TreasuryTransaction, utcnow
from bot.utils.embeds import discord_timestamp, error_embed, format_silver, info_embed, success_embed, warning_embed
from bot.utils.helpers import parse_discord_time
from bot.utils.permissions import can_manage_treasury, find_channel

LOGGER = logging.getLogger(__name__)


def _can_tresorerie(member: discord.Member) -> bool:
    return settings.test_mode or can_manage_treasury(member)


def _parse_date(raw: str) -> datetime:
    return parse_discord_time(raw)


def _item_key(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum())


async def build_treasury_embed() -> discord.Embed:
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

    rule = "━" * 26
    debt_block = []
    for debt in debts[:12]:
        name = debt.member.discord_name if debt.member else "?"
        debt_block.append(
            f"**{name}**\n"
            f"{format_silver(debt.remaining_amount)}  ·  id `{debt.id}`  ·  {discord_timestamp(debt.deadline_at, 'R')}"
        )
    res_block = []
    for req in resources[:12]:
        original = req.original_quantity or req.quantity
        res_block.append(
            f"**{req.item_name}**\n"
            f"reste **{req.quantity}** / {original}  ·  id `{req.id}`"
        )

    embed = discord.Embed(
        description=(
            f"-# COFFRE DE GUILDE\n"
            f"{rule}\n\n"
            f"## 💰  TRÉSORERIE\n\n"
            f"# {format_silver(balance)}\n"
            f"-# solde actuel\n\n"
            f"{rule}\n\n"
            f"## DÉPÔT / RETRAIT\n"
            f"**Total donné**    {format_silver(deposited)}\n"
            f"**Total retiré**   {format_silver(withdrawn)}\n\n"
            f"{rule}\n\n"
            f"## DETTES\n"
            f"{chr(10).join(debt_block) if debt_block else '*Aucune dette ouverte.*'}\n\n"
            f"{rule}\n\n"
            f"## DEMANDES DE RESSOURCES\n"
            f"{chr(10).join(res_block) if res_block else '*Aucune demande en cours.*'}"
        ),
        color=discord.Color.gold(),
    )
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


async def _credit_silver(session, *, donor: discord.Member, amount: int, note: str, author_id: int) -> None:
    state = await get_treasury_state(session)
    state.current_balance += amount
    state.total_deposited += amount
    db_member = await get_or_create_member(session, discord_id=donor.id, discord_name=donor.display_name)
    score = await session.scalar(select(ContributionScore).where(ContributionScore.member_id == db_member.id))
    if score is None:
        score = ContributionScore(member_id=db_member.id, monthly_period=utcnow().strftime("%Y-%m"))
        session.add(score)
    score.total_silver_donated += amount
    score.silver_donated_monthly += amount
    session.add(
        GuildDonation(
            member_id=db_member.id,
            donation_type="silver",
            amount=amount,
            note=note,
            approved_by_discord_id=author_id,
            approved_at=utcnow(),
        )
    )
    session.add(
        TreasuryTransaction(
            transaction_type="deposit",
            amount=amount,
            balance_after=state.current_balance,
            note=f"{note} | donateur={donor.display_name}",
            author_discord_id=author_id,
        )
    )


class Treasury(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="tresorerie_depot", description="Dépose du silver (crédite le donateur au classement).")
    @app_commands.guild_only()
    @app_commands.describe(montant="Silver déposé", note="Motif", donateur="Qui a donné (obligatoire)")
    async def tresorerie_depot(
        self,
        interaction: discord.Interaction,
        montant: int,
        note: str,
        donateur: discord.Member,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not _can_tresorerie(interaction.user):
            await interaction.followup.send("Grand Trésorier uniquement (ou mode test).", ephemeral=True)
            return
        if montant <= 0:
            await interaction.followup.send(embed=error_embed("Montant invalide"), ephemeral=True)
            return
        donor = donateur
        async with session_scope() as session:
            await _credit_silver(session, donor=donor, amount=montant, note=note, author_id=interaction.user.id)
        from bot.cogs.orders import credit_order_contribution

        await credit_order_contribution(
            self.bot, discord_id=donor.id, kind="silver_donated", amount=montant
        )
        await refresh_treasury_panel(self.bot, interaction.guild)  # type: ignore[arg-type]
        await log_history(
            interaction.guild,  # type: ignore[arg-type]
            "📥 Dépôt silver",
            f"{donor.mention} a déposé **{format_silver(montant)}**\n{note}",
        )
        await interaction.followup.send(
            embed=success_embed("Dépôt enregistré", f"{format_silver(montant)} de {donor.mention}"),
            ephemeral=True,
        )

    @app_commands.command(name="taxe", description="Collecte une taxe (ajoute à la trésorerie sans affecter le classement).")
    @app_commands.guild_only()
    @app_commands.describe(montant="Silver collecté en taxe", note="Motif de la taxe", source="Joueur taxé (optionnel)")
    async def taxe(
        self,
        interaction: discord.Interaction,
        montant: int,
        note: str,
        source: discord.Member | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not _can_tresorerie(interaction.user):
            await interaction.followup.send("Grand Trésorier uniquement (ou mode test).", ephemeral=True)
            return
        if montant <= 0:
            await interaction.followup.send(embed=error_embed("Montant invalide"), ephemeral=True)
            return
        async with session_scope() as session:
            state = await get_treasury_state(session)
            state.current_balance += montant
            state.total_deposited += montant
            source_name = source.display_name if source else "Source non spécifiée"
            session.add(
                TreasuryTransaction(
                    transaction_type="deposit",
                    amount=montant,
                    balance_after=state.current_balance,
                    note=f"TAXE: {note} | source={source_name}",
                    author_discord_id=interaction.user.id,
                )
            )
        await refresh_treasury_panel(self.bot, interaction.guild)  # type: ignore[arg-type]
        source_text = f" de {source.mention}" if source else ""
        await log_history(
            interaction.guild,  # type: ignore[arg-type]
            "🏛️ Taxe collectée",
            f"**{format_silver(montant)}** collectés{source_text}\n{note}",
        )
        await interaction.followup.send(
            embed=success_embed("Taxe enregistrée", f"{format_silver(montant)}{source_text}"),
            ephemeral=True,
        )

    @app_commands.command(name="tresorerie_retrait", description="Retire du silver de la trésorerie.")
    @app_commands.guild_only()
    async def tresorerie_retrait(self, interaction: discord.Interaction, montant: int, note: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not _can_tresorerie(interaction.user):
            await interaction.followup.send("Grand Trésorier uniquement (ou mode test).", ephemeral=True)
            return
        if montant <= 0:
            await interaction.followup.send(embed=error_embed("Montant invalide"), ephemeral=True)
            return
        async with session_scope() as session:
            state = await get_treasury_state(session)
            if state.current_balance < montant:
                await interaction.followup.send(
                    embed=error_embed("Solde insuffisant", format_silver(state.current_balance)),
                    ephemeral=True,
                )
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
        await refresh_treasury_panel(self.bot, interaction.guild)  # type: ignore[arg-type]
        await log_history(interaction.guild, "📤 Retrait", f"{interaction.user.mention} -{format_silver(montant)}\n{note}")  # type: ignore[arg-type]
        await interaction.followup.send(embed=success_embed("Retrait enregistré", format_silver(montant)), ephemeral=True)

    @app_commands.command(name="dette_ajouter", description="Ajoute une dette à un membre.")
    @app_commands.guild_only()
    @app_commands.describe(deadline="<t:1787511600:R>")
    async def dette_ajouter(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        montant: int,
        deadline: str,
        raison: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not _can_tresorerie(interaction.user):
            await interaction.followup.send("Permission insuffisante.", ephemeral=True)
            return
        try:
            ends = _parse_date(deadline)
        except ValueError as exc:
            await interaction.followup.send(embed=error_embed("Deadline", str(exc)), ephemeral=True)
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
        await refresh_treasury_panel(self.bot, interaction.guild)  # type: ignore[arg-type]
        await log_history(
            interaction.guild,  # type: ignore[arg-type]
            "📋 Dette ajoutée",
            f"{membre.mention} — {format_silver(montant)}\nÉchéance {discord_timestamp(ends, 'R')}\n{raison}\nid `{debt_id}`",
        )
        await interaction.followup.send(embed=success_embed("Dette créée", f"id `{debt_id}`"), ephemeral=True)

    @app_commands.command(name="dette_rembourser", description="Marque une dette comme remboursée.")
    @app_commands.guild_only()
    async def dette_rembourser(self, interaction: discord.Interaction, id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not _can_tresorerie(interaction.user):
            await interaction.followup.send("Permission insuffisante.", ephemeral=True)
            return
        async with session_scope() as session:
            debt = await session.get(Debt, id)
            if debt is None or debt.status != "open":
                await interaction.followup.send(embed=error_embed("Dette introuvable"), ephemeral=True)
                return
            debt.status = "repaid"
            debt.remaining_amount = 0
            debt.repaid_at = utcnow()
        await refresh_treasury_panel(self.bot, interaction.guild)  # type: ignore[arg-type]
        await log_history(interaction.guild, "✅ Dette remboursée", f"id `{id}` par {interaction.user.mention}")  # type: ignore[arg-type]
        await interaction.followup.send(embed=success_embed("Dette soldée"), ephemeral=True)

    @app_commands.command(name="ressource_ajouter", description="Ajoute une demande de ressource visible en trésorerie.")
    @app_commands.guild_only()
    async def ressource_ajouter(
        self,
        interaction: discord.Interaction,
        item: str,
        quantite: int,
        demandeur: discord.Member,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not _can_tresorerie(interaction.user):
            await interaction.followup.send("Permission insuffisante.", ephemeral=True)
            return
        async with session_scope() as session:
            db_member = await get_or_create_member(session, discord_id=demandeur.id, discord_name=demandeur.display_name)
            req = ResourceRequest(
                item_name=item,
                quantity=quantite,
                original_quantity=quantite,
                requester_member_id=db_member.id,
                created_by_discord_id=interaction.user.id,
            )
            session.add(req)
            await session.flush()
            rid = req.id
        await refresh_treasury_panel(self.bot, interaction.guild)  # type: ignore[arg-type]
        await log_history(interaction.guild, "📦 Demande ressource", f"{quantite}× {item} par {demandeur.mention} (id `{rid}`)")  # type: ignore[arg-type]
        await interaction.followup.send(embed=success_embed("Demande ajoutée", f"id `{rid}`"), ephemeral=True)

    @app_commands.command(name="ressource_supprimer", description="Débite une quantité sur une demande (id + nombre).")
    @app_commands.guild_only()
    @app_commands.describe(id="ID de la demande", quantite="Quantité ajoutée", donateur="Qui a apporté (obligatoire)")
    async def ressource_supprimer(
        self,
        interaction: discord.Interaction,
        id: int,
        quantite: int,
        donateur: discord.Member,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not _can_tresorerie(interaction.user):
            await interaction.followup.send("Permission insuffisante.", ephemeral=True)
            return
        if quantite <= 0:
            await interaction.followup.send(embed=error_embed("Quantité invalide"), ephemeral=True)
            return
        async with session_scope() as session:
            req = await session.get(ResourceRequest, id)
            if req is None or req.status != "open":
                await interaction.followup.send(embed=error_embed("Demande introuvable"), ephemeral=True)
                return
            if req.original_quantity is None:
                req.original_quantity = req.quantity
            before = req.quantity
            req.quantity = max(0, req.quantity - quantite)
            after = req.quantity
            if req.quantity == 0:
                req.status = "closed"
                req.fulfilled_at = utcnow()
            item_label = req.item_name
        donor = donateur
        from bot.cogs.orders import credit_order_contribution

        await credit_order_contribution(
            self.bot,
            discord_id=donor.id,
            kind="item_donated",
            amount=quantite,
            item_name=item_label,
        )
        await refresh_treasury_panel(self.bot, interaction.guild)  # type: ignore[arg-type]
        await log_history(
            interaction.guild,  # type: ignore[arg-type]
            "📦 Ressource ajoutée",
            f"{donor.mention} a ajouté **{quantite}× {item_label}** (`{id}`)\n{before} → **{after}**",
        )
        await interaction.followup.send(
            embed=success_embed("Demande mise à jour", f"{item_label} : {before} → **{after}** restants"),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Treasury(bot))
