"""Phase 3 — Ordres prioritaires."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.config import settings
from bot.tasks.order_cleanup import run_order_cleanup
from bot.database.crud import get_or_create_member, next_order_number
from bot.database.engine import session_scope
from bot.database.models import ContributionScore, Order, OrderParticipant, utcnow
from bot.utils.embeds import (
    discord_timestamp,
    error_embed,
    format_order_number,
    info_embed,
    progress_bar,
    success_embed,
    warning_embed,
)
from bot.utils.permissions import can_manage_orders, find_channel

LOGGER = logging.getLogger(__name__)
TZ = ZoneInfo("Europe/Berlin")

PRIORITY_META = {
    "low": ("🟢 Basse", 10, discord.Color.green()),
    "medium": ("🟡 Moyenne", 25, discord.Color.gold()),
    "high": ("🟠 Haute", 50, discord.Color.orange()),
    "critical": ("🔴 Critique", 100, discord.Color.red()),
}

OBJECTIVE_TYPES = {
    "gathering_fame": "Fame gathering (auto plus tard)",
    "pve_fame": "Fame PvE (auto plus tard)",
    "silver_donated": "Silver donné",
    "item_donated": "Item donné",
    "manual": "Progression manuelle",
}

REWARD_TYPES = {
    "winner": "🏆 Winner Takes All",
    "podium": "🥇🥈🥉 Podium",
    "all": "👥 Pour tous les contributeurs",
    "mixed": "🥇 Podium + 👥 autres",
}


def _can_manage(member: discord.Member) -> bool:
    return settings.test_mode or can_manage_orders(member)


_TS_RE = re.compile(r"<t:(\d+)(?::[tTdDfFR])?>")


def _parse_deadline(raw: str) -> datetime:
    text = raw.strip()
    match = _TS_RE.search(text)
    if match:
        return datetime.fromtimestamp(int(match.group(1)), tz=UTC)
    if text.isdigit() and len(text) >= 10:
        return datetime.fromtimestamp(int(text), tz=UTC)
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=TZ)
        except ValueError:
            continue
    raise ValueError("Deadline : `<t:1787511600:R>` ou `JJ/MM/AAAA HH:MM`")


def _reward_lines(order: Order) -> str:
    kind = REWARD_TYPES.get(order.reward_type, order.reward_type)
    lines = [kind]
    if order.reward_type == "winner" and order.reward_winner:
        lines.append(f"• Gagnant : {order.reward_winner}")
    if order.reward_type in {"podium", "mixed"}:
        if order.reward_gold:
            lines.append(f"🥇 {order.reward_gold}")
        if order.reward_silver:
            lines.append(f"🥈 {order.reward_silver}")
        if order.reward_bronze:
            lines.append(f"🥉 {order.reward_bronze}")
    if order.reward_type == "all" and order.reward_others:
        lines.append(f"• Tous : {order.reward_others}")
    if order.reward_type == "mixed" and order.reward_others:
        lines.append(f"👥 Autres : {order.reward_others}")
    return "\n".join(lines)


def _mention(discord_id: int | None) -> str:
    if not discord_id:
        return "—"
    return f"<@{discord_id}>"


def build_order_embed(order: Order) -> discord.Embed:
    label, points, color = PRIORITY_META.get(order.priority, ("?", 0, discord.Color.greyple()))
    emoji = label.split()[0]
    percent = 0 if order.target_amount <= 0 else min(100, int(order.current_amount * 100 / order.target_amount))
    parts = sorted(order.participants, key=lambda p: p.contribution_amount, reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    people = []
    for idx, part in enumerate(parts[:15]):
        medal = medals[idx] if idx < 3 else "•"
        name = part.member.discord_name if part.member else f"#{part.member_id}"
        mention = f"<@{part.member.discord_id}>" if part.member else name
        people.append(f"{medal} {mention} — **{part.contribution_percent:.0f}%** ({part.contribution_amount})")

    status_label = {
        "active": "🟢 Actif",
        "completed": "✔️ Terminé",
        "cancelled": "❌ Annulé",
        "expired": "⏰ Expiré",
    }.get(order.status, order.status)

    bar = progress_bar(order.current_amount, order.target_amount, width=28)
    deadline = order.deadline_at
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)

    close_line = ""
    if order.status == "cancelled":
        close_line = f"\n❌ Annulé par {_mention(order.cancelled_by_discord_id)}"
        if order.cancelled_at:
            close_line += f" — {discord_timestamp(order.cancelled_at, 'R')}"
    elif order.status in {"completed", "expired"}:
        who = "la deadline" if order.close_reason == "deadline" else _mention(order.completed_by_discord_id)
        close_line = f"\n✔️ Clôturé par {who}"
        if order.completed_at:
            close_line += f" — {discord_timestamp(order.completed_at, 'R')}"

    item_line = f"\n**Item :** {order.objective_item_name}" if order.objective_item_name else ""
    description = (
        f"# {emoji} ORDRE {format_order_number(order.order_number)}\n"
        f"## {order.title}\n\n"
        f"{order.description}\n\n"
        f"### 📊 Progression — {percent}%\n"
        f"`{bar}`\n"
        f"**{order.current_amount:,} / {order.target_amount:,}**"
        f"{close_line}"
    )

    embed = discord.Embed(description=description, color=color)
    embed.add_field(
        name="⏰ Deadline",
        value=f"{discord_timestamp(deadline, 'F')}\nSe termine {discord_timestamp(deadline, 'R')}",
        inline=False,
    )
    embed.add_field(name="📌 Statut", value=status_label, inline=True)
    embed.add_field(name="🎯 Type", value=OBJECTIVE_TYPES.get(order.objective_type, order.objective_type) + item_line, inline=True)
    embed.add_field(name="🏆 Points", value=f"+{points} / contributeur", inline=True)
    embed.add_field(name="👤 Créé par", value=_mention(order.creator_discord_id), inline=True)
    embed.add_field(name="🎁 Récompenses", value=_reward_lines(order), inline=False)
    embed.add_field(
        name=f"👥 Participants ({len(parts)})",
        value="\n".join(people) or "*Personne pour le moment — clique **Accepter***",
        inline=False,
    )
    embed.set_footer(text="Albion PPCF • Fort Sterling")
    return embed


class OrderButtons(discord.ui.View):
    def __init__(self, order_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Accepter", emoji="✅", style=discord.ButtonStyle.success, custom_id=f"order:accept:{order_id}"))
        self.add_item(discord.ui.Button(label="Progression", emoji="📊", style=discord.ButtonStyle.primary, custom_id=f"order:progress:{order_id}"))
        self.add_item(discord.ui.Button(label="Terminer", emoji="✔️", style=discord.ButtonStyle.secondary, custom_id=f"order:complete:{order_id}"))
        self.add_item(discord.ui.Button(label="Annuler", emoji="❌", style=discord.ButtonStyle.danger, custom_id=f"order:cancel:{order_id}"))


class ProgressModal(discord.ui.Modal, title="Ajouter une progression"):
    participant = discord.ui.TextInput(label="Pseudo Discord du participant", required=True, max_length=120)
    amount = discord.ui.TextInput(label="Quantité à AJOUTER", placeholder="ex: 250", required=True, max_length=12)

    def __init__(self, order_id: int) -> None:
        super().__init__()
        self.order_id = order_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            qty = int(str(self.amount).replace(" ", ""))
        except ValueError:
            await interaction.response.send_message(embed=error_embed("Quantité invalide"), ephemeral=True)
            return
        if qty <= 0:
            await interaction.response.send_message(embed=error_embed("La quantité doit être > 0"), ephemeral=True)
            return

        needle = str(self.participant).strip().lower()
        async with session_scope() as session:
            order = await session.get(Order, self.order_id, options=[selectinload(Order.participants).selectinload(OrderParticipant.member)])
            if order is None or order.status != "active":
                await interaction.response.send_message(embed=error_embed("Ordre introuvable ou inactif"), ephemeral=True)
                return
            target = None
            for part in order.participants:
                name = (part.member.discord_name if part.member else "").lower()
                if needle in name or needle == str(part.member.discord_id if part.member else ""):
                    target = part
                    break
            if target is None:
                await interaction.response.send_message(
                    embed=error_embed("Participant introuvable", "Il doit d'abord cliquer Accepter."),
                    ephemeral=True,
                )
                return
            target.contribution_amount += qty
            order.current_amount = sum(p.contribution_amount for p in order.participants)
            total = order.current_amount or 1
            for part in order.participants:
                part.contribution_percent = part.contribution_amount * 100 / total
            await session.flush()
            await refresh_order_message(interaction.client, order)
        await interaction.response.send_message(embed=success_embed("Progression ajoutée", f"+{qty}"), ephemeral=True)


async def _load_order(session, order_id: int) -> Order | None:
    result = await session.execute(
        select(Order).options(selectinload(Order.participants).selectinload(OrderParticipant.member)).where(Order.id == order_id)
    )
    return result.scalar_one_or_none()


async def refresh_order_message(bot: commands.Bot, order: Order) -> None:
    if not order.channel_id or not order.message_id:
        return
    channel = bot.get_channel(order.channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        message = await channel.fetch_message(order.message_id)
        view = OrderButtons(order.id) if order.status == "active" else None
        await message.edit(embed=build_order_embed(order), view=view)
    except discord.HTTPException:
        LOGGER.exception("Maj message ordre #%s impossible", order.order_number)


async def complete_order(
    bot: commands.Bot,
    order_id: int,
    *,
    actor_id: int | None = None,
    reason: str = "manual",
) -> Order | None:
    async with session_scope() as session:
        order = await _load_order(session, order_id)
        if order is None or order.status != "active":
            return None
        order.status = "expired" if reason == "deadline" else "completed"
        order.completed_at = utcnow()
        order.completed_by_discord_id = actor_id
        order.close_reason = reason
        _, points, _ = PRIORITY_META.get(order.priority, ("", 0, None))
        contributors = [p for p in order.participants if p.contribution_amount > 0]
        contributors.sort(key=lambda p: p.contribution_amount, reverse=True)
        for part in contributors:
            part.points_awarded = points
            score = await session.scalar(select(ContributionScore).where(ContributionScore.member_id == part.member_id))
            if score is None:
                score = ContributionScore(member_id=part.member_id, monthly_period=utcnow().strftime("%Y-%m"))
                session.add(score)
            score.order_points_all_time += points
            score.order_points_monthly += points
        await session.flush()
        ranking = list(contributors)
        snapshot = {
            "title": order.title,
            "number": order.order_number,
            "reward_type": order.reward_type,
            "rewards": {
                "winner": order.reward_winner,
                "gold": order.reward_gold,
                "silver": order.reward_silver,
                "bronze": order.reward_bronze,
                "others": order.reward_others,
            },
            "people": [(p.member.discord_id if p.member else 0, p.member.discord_name if p.member else "?", p.contribution_amount) for p in ranking],
        }
        await refresh_order_message(bot, order)

    # DMs hors transaction
    lines = [f"Ordre {format_order_number(snapshot['number'])} **{snapshot['title']}** terminé."]
    medals = ["🥇", "🥈", "🥉"]
    for idx, (_did, name, amt) in enumerate(snapshot["people"]):
        medal = medals[idx] if idx < 3 else "•"
        lines.append(f"{medal} {name} — {amt}")
    recap = "\n".join(lines)
    for idx, (did, _name, _amt) in enumerate(snapshot["people"]):
        reward_txt = ""
        rtype = snapshot["reward_type"]
        rew = snapshot["rewards"]
        if rtype == "winner" and idx == 0:
            reward_txt = rew["winner"] or ""
        elif rtype in {"podium", "mixed"} and idx == 0:
            reward_txt = rew["gold"] or ""
        elif rtype in {"podium", "mixed"} and idx == 1:
            reward_txt = rew["silver"] or ""
        elif rtype in {"podium", "mixed"} and idx == 2:
            reward_txt = rew["bronze"] or ""
        elif rtype == "all" or (rtype == "mixed" and idx > 2):
            reward_txt = rew["others"] or ""
        user = bot.get_user(did) or (await bot.fetch_user(did) if did else None)
        if user is None:
            continue
        try:
            extra = f"\n🎁 Récompense : {reward_txt}" if reward_txt else ""
            await user.send(embed=info_embed("Ordre terminé", recap + extra))
        except discord.HTTPException:
            pass
    return order


class Orders(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ordre_creer", description="Crée un ordre prioritaire.")
    @app_commands.guild_only()
    @app_commands.describe(
        titre="Titre de l'ordre",
        description="Détail de la mission",
        priorite="Basse / moyenne / haute / critique",
        objectif="Quantité cible (ex: 5000)",
        type_objectif="Comment on mesure la progression",
        deadline="JJ/MM/AAAA HH:MM",
        type_recompense="winner / podium / all / mixed",
        recompense_principale="Winner-takes-all, or, ou récompense pour tous",
        recompense_argent="2e (podium/mixed)",
        recompense_bronze="3e (podium/mixed)",
        recompense_autres="Autres contributeurs (mixed ou all)",
        item="Nom d'item si type item_donated",
    )
    @app_commands.choices(
        priorite=[
            app_commands.Choice(name="🟢 Basse (+10)", value="low"),
            app_commands.Choice(name="🟡 Moyenne (+25)", value="medium"),
            app_commands.Choice(name="🟠 Haute (+50)", value="high"),
            app_commands.Choice(name="🔴 Critique (+100)", value="critical"),
        ],
        type_objectif=[app_commands.Choice(name=v, value=k) for k, v in OBJECTIVE_TYPES.items()],
        type_recompense=[app_commands.Choice(name=v, value=k) for k, v in REWARD_TYPES.items()],
    )
    async def ordre_creer(
        self,
        interaction: discord.Interaction,
        titre: str,
        description: str,
        priorite: app_commands.Choice[str],
        objectif: int,
        type_objectif: app_commands.Choice[str],
        deadline: str,
        type_recompense: app_commands.Choice[str],
        recompense_principale: str,
        recompense_argent: str | None = None,
        recompense_bronze: str | None = None,
        recompense_autres: str | None = None,
        item: str | None = None,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not _can_manage(interaction.user):
            await interaction.response.send_message("Seuls Seigneur de Guerre / Grand Trésorier (ou mode test).", ephemeral=True)
            return
        if objectif <= 0:
            await interaction.response.send_message(embed=error_embed("Objectif invalide"), ephemeral=True)
            return
        try:
            ends = _parse_deadline(deadline)
        except ValueError as exc:
            await interaction.response.send_message(embed=error_embed("Deadline", str(exc)), ephemeral=True)
            return

        guild = interaction.guild
        assert guild is not None
        channel = find_channel(guild, "priority_orders")
        if channel is None:
            await interaction.response.send_message(embed=error_embed("Salon #ordre-prioritaire introuvable"), ephemeral=True)
            return

        _, points, _ = PRIORITY_META[priorite.value]
        rtype = type_recompense.value
        async with session_scope() as session:
            number = await next_order_number(session)
            order = Order(
                order_number=number,
                title=titre,
                description=description,
                priority=priorite.value,
                objective_type=type_objectif.value,
                objective_item_name=item,
                target_amount=objectif,
                deadline_at=ends,
                reward_type=rtype,
                reward_winner=recompense_principale if rtype == "winner" else None,
                reward_gold=recompense_principale if rtype in {"podium", "mixed"} else None,
                reward_silver=recompense_argent,
                reward_bronze=recompense_bronze,
                reward_others=recompense_autres if rtype in {"all", "mixed"} else (recompense_principale if rtype == "all" else None),
                points_value=points,
                creator_discord_id=interaction.user.id,
            )
            if rtype == "all":
                order.reward_others = recompense_principale
            session.add(order)
            await session.flush()
            order_id = order.id
            loaded = await _load_order(session, order_id)
            assert loaded is not None
            message = await channel.send(embed=build_order_embed(loaded), view=OrderButtons(order_id))
            loaded.channel_id = channel.id
            loaded.message_id = message.id

        await interaction.response.send_message(
            embed=success_embed("Ordre créé", f"{format_order_number(number)} posté dans {channel.mention}"),
            ephemeral=True,
        )

    @app_commands.command(name="ordre_info", description="Détails d'un ordre (actif ou passé).")
    @app_commands.describe(numero="Numéro visible, ex: 1 pour #001")
    async def ordre_info(self, interaction: discord.Interaction, numero: int) -> None:
        async with session_scope() as session:
            result = await session.execute(
                select(Order)
                .options(selectinload(Order.participants).selectinload(OrderParticipant.member))
                .where(Order.order_number == numero)
            )
            order = result.scalar_one_or_none()
        if order is None:
            await interaction.response.send_message(embed=error_embed("Ordre introuvable"), ephemeral=True)
            return
        await interaction.response.send_message(embed=build_order_embed(order), ephemeral=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type is not discord.InteractionType.component or not interaction.data:
            return
        custom_id = str(interaction.data.get("custom_id") or "")
        if not custom_id.startswith("order:"):
            return
        parts = custom_id.split(":")
        if len(parts) != 3:
            return
        _, action, raw_id = parts
        try:
            order_id = int(raw_id)
        except ValueError:
            return
        await self._handle(interaction, action, order_id)

    async def _handle(self, interaction: discord.Interaction, action: str, order_id: int) -> None:
        user = interaction.user
        if action == "progress":
            if not isinstance(user, discord.Member) or not _can_manage(user):
                await interaction.response.send_message("Réservé aux gestionnaires d'ordres.", ephemeral=True)
                return
            await interaction.response.send_modal(ProgressModal(order_id))
            return

        if action == "accept":
            async with session_scope() as session:
                order = await _load_order(session, order_id)
                if order is None or order.status != "active":
                    await interaction.response.send_message(embed=error_embed("Ordre inactif"), ephemeral=True)
                    return
                member = await get_or_create_member(session, discord_id=user.id, discord_name=user.display_name)
                already = any(p.member_id == member.id for p in order.participants)
                if already:
                    await interaction.response.send_message("Tu es déjà inscrit.", ephemeral=True)
                    return
                session.add(OrderParticipant(order_id=order.id, member_id=member.id))
                await session.flush()

            async with session_scope() as session:
                order = await _load_order(session, order_id)
                assert order is not None
                embed = build_order_embed(order)
                view = OrderButtons(order.id)
            if interaction.message is not None:
                try:
                    await interaction.response.edit_message(embed=embed, view=view)
                    await interaction.followup.send(embed=success_embed("Inscription OK"), ephemeral=True)
                    return
                except discord.HTTPException:
                    pass
            await refresh_order_message(self.bot, order)
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=success_embed("Inscription OK"), ephemeral=True)
            return

        if action in {"complete", "cancel"}:
            if not isinstance(user, discord.Member) or not _can_manage(user):
                await interaction.response.send_message("Permission insuffisante.", ephemeral=True)
                return
            if action == "cancel":
                async with session_scope() as session:
                    order = await _load_order(session, order_id)
                    if order is None or order.status != "active":
                        await interaction.response.send_message(embed=error_embed("Déjà clos"), ephemeral=True)
                        return
                    order.status = "cancelled"
                    order.cancelled_at = utcnow()
                    order.cancelled_by_discord_id = user.id
                    order.close_reason = "manual"
                    await refresh_order_message(self.bot, order)
                await interaction.response.send_message(
                    embed=warning_embed("Ordre annulé", f"Annulé par {user.mention}"),
                    ephemeral=True,
                )
                return
            await interaction.response.defer(ephemeral=True)
            done = await complete_order(self.bot, order_id, actor_id=user.id, reason="manual")
            if done is None:
                await interaction.followup.send(embed=error_embed("Impossible de terminer"), ephemeral=True)
            else:
                await interaction.followup.send(
                    embed=success_embed("Ordre terminé", "Reste 24h ici puis archive dans #ordres-passés."),
                    ephemeral=True,
                )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Orders(bot))
