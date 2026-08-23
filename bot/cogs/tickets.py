"""Phase 4 — Déclarations / tickets."""

from __future__ import annotations

import logging
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.config import settings
from bot.database.crud import get_or_create_member, get_treasury_state, next_ticket_number
from bot.database.engine import session_scope
from bot.database.models import ContributionScore, GuildDonation, Ticket, TreasuryTransaction, utcnow
from bot.utils.embeds import error_embed, format_silver, info_embed, success_embed, warning_embed
from bot.utils.permissions import can_manage_treasury, find_channel, find_role, is_officer

LOGGER = logging.getLogger(__name__)

TICKET_TYPES = {
    "donate": "💰 Don",
    "craft": "🔨 Craft / ressource",
    "report": "⚠️ Problème",
    "other": "💬 Autre",
}


def _staff_overwrites(guild: discord.Guild, opener: discord.Member) -> dict:
    overwrites: dict = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        opener: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    for key in ("guild_master", "grand_treasurer", "officer", "war_lord"):
        role = find_role(guild, key)
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    return overwrites


async def _tickets_category(guild: discord.Guild) -> discord.CategoryChannel | None:
    for cat in guild.categories:
        if "ticket" in cat.name.lower() or "déclar" in cat.name.lower() or "declar" in cat.name.lower():
            return cat
    decl = find_channel(guild, "declaration")
    if decl and decl.category:
        return decl.category
    try:
        return await guild.create_category("🎫 tickets")
    except discord.HTTPException:
        return None


class TicketCloseView(discord.ui.View):
    def __init__(self, ticket_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Fermer", emoji="🔒", style=discord.ButtonStyle.danger, custom_id=f"ticket:close:{ticket_id}"))


class DonationReviewView(discord.ui.View):
    def __init__(self, ticket_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Approuver", emoji="✅", style=discord.ButtonStyle.success, custom_id=f"ticket:approve:{ticket_id}"))
        self.add_item(discord.ui.Button(label="Refuser", emoji="❌", style=discord.ButtonStyle.danger, custom_id=f"ticket:deny:{ticket_id}"))


class DeclarationView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Faire un don", emoji="💰", style=discord.ButtonStyle.success, custom_id="ticket:open:donate")
    async def donate(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await handle_ticket_button(interaction, "open", "donate")

    @discord.ui.button(label="Craft / ressource", emoji="🔨", style=discord.ButtonStyle.primary, custom_id="ticket:open:craft")
    async def craft(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await handle_ticket_button(interaction, "open", "craft")

    @discord.ui.button(label="Signaler un problème", emoji="⚠️", style=discord.ButtonStyle.danger, custom_id="ticket:open:report")
    async def report(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await handle_ticket_button(interaction, "open", "report")

    @discord.ui.button(label="Autre", emoji="💬", style=discord.ButtonStyle.secondary, custom_id="ticket:open:other")
    async def other(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await handle_ticket_button(interaction, "open", "other")


class DonateModal(discord.ui.Modal, title="Déclarer un don"):
    kind = discord.ui.TextInput(label="Type (silver ou item)", placeholder="silver", required=True, max_length=10)
    amount = discord.ui.TextInput(label="Montant / quantité", placeholder="500000", required=True, max_length=16)
    extra = discord.ui.TextInput(label="Nom item ou n° ordre (optionnel)", required=False, max_length=80)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await create_ticket(
            interaction,
            "donate",
            f"{self.kind} · {self.amount}",
            f"Type: {self.kind}\nQuantité: {self.amount}\nDétail: {self.extra or '—'}",
        )


class FreeModal(discord.ui.Modal):
    titre = discord.ui.TextInput(label="Titre", required=True, max_length=80)
    details = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=True, max_length=1000)

    def __init__(self, ticket_type: str) -> None:
        super().__init__(title=TICKET_TYPES.get(ticket_type, "Déclaration"))
        self.ticket_type = ticket_type

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await create_ticket(interaction, self.ticket_type, str(self.titre), str(self.details))


async def create_ticket(interaction: discord.Interaction, ticket_type: str, title: str, description: str) -> None:
    guild = interaction.guild
    user = interaction.user
    if guild is None or not isinstance(user, discord.Member):
        await interaction.response.send_message("Utilise cette action sur le serveur.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    category = await _tickets_category(guild)
    async with session_scope() as session:
        member = await get_or_create_member(session, discord_id=user.id, discord_name=user.display_name)
        number = await next_ticket_number(session)
        slug = "".join(ch for ch in user.display_name.lower() if ch.isalnum())[:12] or "membre"
        channel_name = f"ticket-{number:03d}-{slug}"
        try:
            channel = await guild.create_text_channel(
                channel_name,
                category=category,
                overwrites=_staff_overwrites(guild, user),
                topic=f"{TICKET_TYPES[ticket_type]} — {user.display_name}",
            )
        except discord.HTTPException:
            LOGGER.exception("Création salon ticket impossible")
            await interaction.followup.send(embed=error_embed("Impossible de créer le salon (permissions bot)."), ephemeral=True)
            return

        ticket = Ticket(
            ticket_number=number,
            ticket_type=ticket_type,
            channel_id=channel.id,
            member_id=member.id,
            title=title[:180],
            description=description,
        )
        session.add(ticket)
        await session.flush()
        ticket_id = ticket.id

    embed = info_embed(f"🎫 Ticket #{number:03d} — {TICKET_TYPES[ticket_type]}", description)
    embed.add_field(name="Auteur", value=user.mention, inline=True)
    embed.add_field(name="Sujet", value=title, inline=True)
    close_view = TicketCloseView(ticket_id)
    await channel.send(content=user.mention, embed=embed, view=close_view)
    close_view.stop()

    if ticket_type == "donate":
        for member_obj in guild.members:
            if can_manage_treasury(member_obj) and not member_obj.bot:
                try:
                    review = DonationReviewView(ticket_id)
                    await member_obj.send(
                        embed=warning_embed("Don à valider", f"{user.mention} — {title}\n{channel.mention}"),
                        view=review,
                    )
                    review.stop()
                except discord.HTTPException:
                    pass

    await interaction.followup.send(embed=success_embed("Ticket ouvert", channel.mention), ephemeral=True)


async def close_ticket(bot: commands.Bot, ticket_id: int, closer_id: int) -> None:
    async with session_scope() as session:
        ticket = await session.get(Ticket, ticket_id)
        if ticket is None or ticket.status != "open":
            return
        channel_id = ticket.channel_id
        number = ticket.ticket_number
        ttype = ticket.ticket_type
        title = ticket.title or ""
        ticket.status = "closed"
        ticket.closed_at = utcnow()
        ticket.closed_by_discord_id = closer_id

    channel = bot.get_channel(channel_id)
    transcript = []
    guild = None
    if isinstance(channel, discord.TextChannel):
        guild = channel.guild
        async for msg in channel.history(limit=50, oldest_first=True):
            transcript.append(f"**{msg.author.display_name}**: {msg.content[:200]}" if msg.content else f"**{msg.author.display_name}**: *(embed)*")
        try:
            await channel.delete(reason="Ticket fermé")
        except discord.HTTPException:
            pass

    if guild:
        logs = find_channel(guild, "ticket_logs")
        if logs:
            body = "\n".join(transcript[-20:]) or "*vide*"
            await logs.send(
                embed=info_embed(
                    f"📁 Ticket #{number:03d} fermé",
                    f"Type: {TICKET_TYPES.get(ttype, ttype)}\nSujet: {title}\n\n{body[:1800]}",
                )
            )


async def handle_ticket_button(interaction: discord.Interaction, action: str, payload: str) -> None:
    user = interaction.user
    if action == "open":
        if payload == "donate":
            await interaction.response.send_modal(DonateModal())
        else:
            await interaction.response.send_modal(FreeModal(payload))
        return

    ticket_id = int(payload)
    if action == "close":
        await interaction.response.defer(ephemeral=True)
        await close_ticket(interaction.client, ticket_id, user.id)
        if not interaction.response.is_done():
            await interaction.followup.send("Ticket fermé.", ephemeral=True)
        else:
            try:
                await interaction.followup.send("Ticket fermé.", ephemeral=True)
            except discord.HTTPException:
                pass
        return

    if action in {"approve", "deny"}:
        if not isinstance(user, discord.Member) or not (settings.test_mode or can_manage_treasury(user) or is_officer(user)):
            await interaction.response.send_message("Réservé au trésorier.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with session_scope() as session:
            ticket = await session.get(Ticket, ticket_id)
            if ticket is None:
                await interaction.followup.send("Ticket introuvable.", ephemeral=True)
                return
            desc = ticket.description or ""
            member_id = ticket.member_id
            if action == "approve" and ticket.ticket_type == "donate":
                amount = 0
                for line in desc.splitlines():
                    if line.lower().startswith("quantité"):
                        raw = "".join(ch for ch in line if ch.isdigit())
                        if raw:
                            amount = int(raw)
                kind = "silver" if "silver" in desc.lower() else "item"
                donation = GuildDonation(
                    member_id=member_id,
                    donation_type=kind,
                    amount=amount or 0,
                    note=desc,
                    approved_by_discord_id=user.id,
                    approved_at=utcnow(),
                    ticket_id=ticket.id,
                )
                session.add(donation)
                if kind == "silver" and amount:
                    state = await get_treasury_state(session)
                    state.current_balance += amount
                    state.total_deposited += amount
                    session.add(
                        TreasuryTransaction(
                            transaction_type="donation",
                            amount=amount,
                            balance_after=state.current_balance,
                            note="Don validé via ticket",
                            author_discord_id=user.id,
                        )
                    )
                    score = await session.scalar(select(ContributionScore).where(ContributionScore.member_id == member_id))
                    if score:
                        score.total_silver_donated += amount
        if action == "approve":
            if interaction.guild:
                from bot.cogs.treasury import log_history, refresh_treasury_panel

                await refresh_treasury_panel(interaction.client, interaction.guild)
                await log_history(interaction.guild, "✅ Don approuvé", f"Par {user.mention}")
            await close_ticket(interaction.client, ticket_id, user.id)
            await interaction.followup.send(embed=success_embed("Don approuvé, ticket fermé."), ephemeral=True)
        else:
            await close_ticket(interaction.client, ticket_id, user.id)
            await interaction.followup.send(embed=warning_embed("Don refusé, ticket fermé."), ephemeral=True)


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(DeclarationView())

    @app_commands.command(name="setup_declaration", description="Poste le panneau de déclaration dans #declaration.")
    @app_commands.guild_only()
    async def setup_declaration(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not (settings.test_mode or is_officer(interaction.user)):
            await interaction.response.send_message("Permission insuffisante.", ephemeral=True)
            return
        channel = find_channel(interaction.guild, "declaration")
        if channel is None:
            await interaction.response.send_message(embed=error_embed("Salon #declaration introuvable"), ephemeral=True)
            return
        embed = info_embed(
            "✉️ Déclarations",
            "Choisis un bouton pour ouvrir un ticket privé avec le staff.",
        )
        await channel.send(embed=embed, view=DeclarationView())
        await interaction.response.send_message(embed=success_embed("Panneau posté", channel.mention), ephemeral=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type is not discord.InteractionType.component or not interaction.data:
            return
        custom_id = str(interaction.data.get("custom_id") or "")
        if not custom_id.startswith("ticket:"):
            return
        parts = custom_id.split(":")
        if len(parts) != 3:
            return
        _, action, payload = parts
        if action == "open":
            return
        await handle_ticket_button(interaction, action, payload)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        async with session_scope() as session:
            ticket = await session.scalar(select(Ticket).where(Ticket.channel_id == message.channel.id, Ticket.status == "open"))
            if ticket:
                ticket.last_activity_at = utcnow()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets(bot))
