"""Phase 4 — Déclarations / tickets."""

from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.config import settings
from bot.database.crud import get_or_create_member, next_ticket_number
from bot.database.engine import session_scope
from bot.database.models import Ticket, utcnow
from bot.utils.embeds import error_embed, info_embed, success_embed, warning_embed
from bot.utils.permissions import can_manage_treasury, find_channel, find_role, is_officer

LOGGER = logging.getLogger(__name__)

TICKET_TYPES = {
    "donate": "💰 Don",
    "order": "🎯 Ordre prioritaire",
    "craft": "🔨 Craft / ressource",
    "report": "⚠️ Problème",
    "other": "💬 Autre",
}

NOTIFY_TYPES = {"donate", "order", "craft"}


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


async def notify_treasurers(guild: discord.Guild, embed: discord.Embed, view: discord.ui.View | None = None) -> None:
    """DM chaque membre qui a le rôle Grand Trésorier."""

    if not guild.chunked:
        try:
            await guild.chunk()
        except discord.HTTPException:
            pass
    role = find_role(guild, "grand_treasurer")
    if role is None:
        LOGGER.warning("Rôle Grand Trésorier introuvable, aucun DM envoyé")
        return
    sent = 0
    for member in role.members:
        if member.bot:
            continue
        try:
            await member.send(embed=embed)
            sent += 1
        except discord.HTTPException:
            LOGGER.info("DM Grand Trésorier impossible pour %s", member)
    LOGGER.info("DM ticket envoyé à %s Grand Trésorier(s)", sent)


class TicketActionItem(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"ticket:(?P<action>close|approve|deny):(?P<oid>[0-9]+)",
):
    def __init__(self, action: str, ticket_id: int) -> None:
        meta = {
            "close": ("Fermer", "🔒", discord.ButtonStyle.danger),
            "approve": ("Approuver", "✅", discord.ButtonStyle.success),
            "deny": ("Refuser", "❌", discord.ButtonStyle.danger),
        }
        label, emoji, style = meta[action]
        super().__init__(
            discord.ui.Button(label=label, emoji=emoji, style=style, custom_id=f"ticket:{action}:{ticket_id}")
        )
        self.action = action
        self.ticket_id = ticket_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
        /,
    ) -> TicketActionItem:
        return cls(match["action"], int(match["oid"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await handle_ticket_button(interaction, self.action, str(self.ticket_id))


class TicketCloseView(discord.ui.View):
    def __init__(self, ticket_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(TicketActionItem("close", ticket_id))


class DonationReviewView(discord.ui.View):
    def __init__(self, ticket_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(TicketActionItem("approve", ticket_id))
        self.add_item(TicketActionItem("deny", ticket_id))


class DeclarationView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Don", emoji="💰", style=discord.ButtonStyle.success, custom_id="ticket:open:donate")
    async def donate(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await handle_ticket_button(interaction, "open", "donate")

    @discord.ui.button(label="Ordre prio", emoji="🎯", style=discord.ButtonStyle.primary, custom_id="ticket:open:order")
    async def order(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await handle_ticket_button(interaction, "open", "order")

    @discord.ui.button(label="Craft / stuff", emoji="🔨", style=discord.ButtonStyle.primary, custom_id="ticket:open:craft")
    async def craft(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await handle_ticket_button(interaction, "open", "craft")

    @discord.ui.button(label="Problème", emoji="⚠️", style=discord.ButtonStyle.danger, custom_id="ticket:open:report")
    async def report(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await handle_ticket_button(interaction, "open", "report")

    @discord.ui.button(label="Autre", emoji="💬", style=discord.ButtonStyle.secondary, custom_id="ticket:open:other")
    async def other(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await handle_ticket_button(interaction, "open", "other")


class DonateModal(discord.ui.Modal, title="Déclarer un don"):
    kind = discord.ui.TextInput(label="Type", placeholder="silver  ou  item", required=True, max_length=10)
    amount = discord.ui.TextInput(label="Montant / quantité", placeholder="500000", required=True, max_length=16)
    extra = discord.ui.TextInput(label="Nom de l'item (si item)", required=False, max_length=80)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await create_ticket(
            interaction,
            "donate",
            f"Don {self.kind} × {self.amount}",
            f"**Type :** {self.kind}\n**Quantité :** {self.amount}\n**Item :** {self.extra or '—'}",
        )


class OrderTicketModal(discord.ui.Modal, title="Lier un ordre prioritaire"):
    numero = discord.ui.TextInput(label="Numéro d'ordre", placeholder="7", required=True, max_length=8)
    details = discord.ui.TextInput(
        label="Ce que tu apportes",
        style=discord.TextStyle.paragraph,
        placeholder="Ex: 200 minerai T6 déjà farm",
        required=True,
        max_length=800,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await create_ticket(
            interaction,
            "order",
            f"Ordre #{str(self.numero).strip()}",
            f"**Ordre :** #{str(self.numero).strip()}\n**Contribution :**\n{self.details}",
        )


class CraftModal(discord.ui.Modal, title="Demande craft / ressource"):
    item = discord.ui.TextInput(label="Item ou équipement", placeholder="Ex: bois T6 / set Guardian", required=True, max_length=120)
    quantite = discord.ui.TextInput(label="Quantité", placeholder="100", required=True, max_length=12)
    raison = discord.ui.TextInput(label="Pourquoi / urgence", style=discord.TextStyle.paragraph, required=True, max_length=800)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await create_ticket(
            interaction,
            "craft",
            f"{self.quantite}× {self.item}",
            f"**Besoin :** {self.item}\n**Quantité :** {self.quantite}\n**Motif :**\n{self.raison}",
        )


class ReportModal(discord.ui.Modal, title="Signaler un problème"):
    titre = discord.ui.TextInput(label="Titre court", placeholder="Ex: Comportement en ZvZ", required=True, max_length=80)
    quand = discord.ui.TextInput(label="Quand / où", placeholder="Hier soir, Roads", required=False, max_length=120)
    details = discord.ui.TextInput(label="Décris les faits", style=discord.TextStyle.paragraph, required=True, max_length=1000)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await create_ticket(
            interaction,
            "report",
            str(self.titre),
            f"**Contexte :** {self.quand or '—'}\n\n**Faits :**\n{self.details}",
        )


class OtherModal(discord.ui.Modal, title="Autre demande"):
    titre = discord.ui.TextInput(label="Sujet", required=True, max_length=80)
    details = discord.ui.TextInput(label="Détails", style=discord.TextStyle.paragraph, required=True, max_length=1000)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await create_ticket(
            interaction,
            "other",
            str(self.titre),
            f"**Demande :**\n{self.details}",
        )


async def create_ticket(interaction: discord.Interaction, ticket_type: str, title: str, description: str) -> None:
    guild = interaction.guild
    user = interaction.user
    if guild is None or not isinstance(user, discord.Member):
        if not interaction.response.is_done():
            await interaction.response.send_message("Utilise cette action sur le serveur.", ephemeral=True)
        return

    if not interaction.response.is_done():
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

    embed = discord.Embed(
        description=(
            f"-# TICKET  #{number:03d}\n"
            f"## {TICKET_TYPES[ticket_type]}\n\n"
            f"{description}"
        ),
        color=discord.Color.orange(),
    )
    embed.add_field(name="Auteur", value=user.mention, inline=True)
    embed.add_field(name="Sujet", value=title, inline=True)
    await channel.send(content=user.mention, embed=embed, view=TicketCloseView(ticket_id))

    if ticket_type in NOTIFY_TYPES:
        await notify_treasurers(
            guild,
            warning_embed(
                f"Nouveau ticket — {TICKET_TYPES[ticket_type]}",
                f"{user.mention}\n{title}\n{channel.mention}",
            ),
        )

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
            transcript.append(
                f"**{msg.author.display_name}**: {msg.content[:200]}" if msg.content else f"**{msg.author.display_name}**: *(embed)*"
            )
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
                    f"**Type :** {TICKET_TYPES.get(ttype, ttype)}\n**Sujet :** {title}\n\n{body[:1800]}",
                )
            )


async def handle_ticket_button(interaction: discord.Interaction, action: str, payload: str) -> None:
    user = interaction.user
    if action == "open":
        modals = {
            "donate": DonateModal,
            "order": OrderTicketModal,
            "craft": CraftModal,
            "report": ReportModal,
            "other": OtherModal,
        }
        modal_cls = modals.get(payload)
        if modal_cls is None:
            return
        await interaction.response.send_modal(modal_cls())
        return

    ticket_id = int(payload)
    if action == "close":
        await interaction.response.defer(ephemeral=True)
        await close_ticket(interaction.client, ticket_id, user.id)
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
        if action == "approve" and interaction.guild:
            from bot.cogs.treasury import log_history, refresh_treasury_panel

            await refresh_treasury_panel(interaction.client, interaction.guild)
            await log_history(interaction.guild, "✅ Ticket don traité", f"Par {user.mention}")
        await close_ticket(interaction.client, ticket_id, user.id)
        if action == "approve":
            await interaction.followup.send(embed=success_embed("Approuvé, ticket fermé."), ephemeral=True)
        else:
            await interaction.followup.send(embed=warning_embed("Refusé, ticket fermé."), ephemeral=True)


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(DeclarationView())
        self.bot.add_dynamic_items(TicketActionItem)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(TicketActionItem)

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
