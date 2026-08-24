"""Phase 2 — Onboarding: règles, formulaire profil, validation auto.

Workflow:
1. Arrivée → rôle Non vérifié + bienvenue + bouton profil
2. Accepter les règles + remplir le formulaire
3. Validation → Recrue + annonce + DM commandes utiles
"""

from __future__ import annotations

import logging
from typing import Any

from urllib.parse import quote

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.config import CHANNEL_NAMES, PLAYSTYLE_ROLE_KEYS, ROLE_NAMES, settings
from bot.database.crud import get_or_create_member
from bot.database.engine import session_scope
from bot.database.models import ContributionScore, utcnow
from bot.services.albion_api import AlbionAPIClient, AlbionAPIError
from bot.utils.embeds import error_embed, format_silver, info_embed, success_embed, warning_embed
from bot.utils.permissions import find_channel, find_role, is_guild_master, is_officer

LOGGER = logging.getLogger(__name__)

RANK_LABELS = {
    "unverified": "⚪ Non vérifié",
    "recruit": "🔵 Recrue",
    "knight": "🟣 Chevalier",
    "officer": "🟢 Officier",
    "war_lord": "🟡 Seigneur de Guerre",
    "grand_treasurer": "🔴 Grand Trésorier",
    "guild_master": "🟠 Maître de Guilde",
}

GAMEPLAY_CHOICES: dict[str, str] = {
    "pvp": "⚔️ Combattre d'autres joueurs (PvP)",
    "pve": "🛡️ Affronter des monstres / Donjons (PvE)",
    "gathering": "⛏️ Récolter des ressources (Gathering)",
    "craft": "🔨 Fabriquer et vendre (Craft / Économie)",
    "polyvalent": "🎲 Je veux un peu de tout (Polyvalent)",
}

RULES_CUSTOM_ID = "onboarding:accept_rules"
PROFILE_CUSTOM_ID = "onboarding:open_profile"


def _equip_token(item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    typ = item.get("Type") or item.get("TypeName") or ""
    if not typ:
        return ""
    enchant = int(item.get("EnchantmentLevel") or 0)
    quality = int(item.get("Quality") or 1)
    if enchant:
        return f"{typ}@{enchant}?{quality}"
    return f"{typ}?{quality}"


def character_render_url(equipment: dict[str, Any] | None) -> str | None:
    """Portrait équipé via l'API Render officielle."""

    if not equipment:
        return None
    order = ("MainHand", "OffHand", "Head", "Armor", "Shoes", "Bag", "Cape", "Mount", "Potion", "Food")
    parts = [_equip_token(equipment.get(slot) if isinstance(equipment.get(slot), dict) else None) for slot in order]
    if not any(parts):
        return None
    code = "|".join(parts)
    return f"https://render.albiononline.com/v1/character/{quote(code, safe='@?|_')}.png?size=512"


async def build_member_profile_embed(user: discord.abc.User) -> discord.Embed:
    """Fiche profil : dons, points, fame + portrait équipé Albion."""

    async with session_scope() as session:
        db = await get_or_create_member(session, discord_id=user.id, discord_name=user.display_name)
        score = await session.scalar(select(ContributionScore).where(ContributionScore.member_id == db.id))
        albion_name = db.albion_name
        albion_id = db.albion_player_id
        gameplay = GAMEPLAY_CHOICES.get(db.preferred_gameplay or "", db.preferred_gameplay or "—")
        rank = RANK_LABELS.get(db.current_rank, db.current_rank)
        rules_ok = db.rules_accepted
        profile_ok = db.profile_completed
        donated = score.total_silver_donated if score else 0
        donated_m = score.silver_donated_monthly if score else 0
        pts = score.order_points_all_time if score else 0
        pts_m = score.order_points_monthly if score else 0
        fame = score.total_fame if score else 0

    portrait = None
    extra_stats = ""
    gear_line = ""
    api = AlbionAPIClient()
    try:
        data: dict[str, Any] | None = None
        if albion_id:
            try:
                got = await api.get_player(albion_id)
                data = got if isinstance(got, dict) else None
            except AlbionAPIError:
                data = None
        if data is None and albion_name:
            try:
                search = await api.search_players(albion_name)
                players = (search.get("players") if isinstance(search, dict) else None) or []
                if players and isinstance(players[0], dict):
                    pid = players[0].get("Id")
                    if pid:
                        albion_id = str(pid)
                        async with session_scope() as session:
                            db2 = await get_or_create_member(
                                session, discord_id=user.id, discord_name=user.display_name
                            )
                            db2.albion_player_id = albion_id
                        try:
                            got = await api.get_player(albion_id)
                            data = got if isinstance(got, dict) else players[0]
                        except AlbionAPIError:
                            data = players[0]
            except AlbionAPIError:
                data = None
        if isinstance(data, dict):
            albion_name = data.get("Name") or albion_name
            kf = int(data.get("KillFame") or 0)
            df = int(data.get("DeathFame") or 0)
            extra_stats = f"\n**Kill fame** `{kf:,}`   ·   **Death fame** `{df:,}`".replace(",", " ")
            stats = data.get("LifetimeStatistics") if isinstance(data.get("LifetimeStatistics"), dict) else {}
            pve = int(((stats.get("PvE") or {}) if isinstance(stats.get("PvE"), dict) else {}).get("Total") or 0)
            gath = stats.get("Gathering") if isinstance(stats.get("Gathering"), dict) else {}
            gath_all = gath.get("All") if isinstance(gath.get("All"), dict) else gath
            gathering = int((gath_all or {}).get("Total") or 0) if isinstance(gath_all, dict) else 0
            craft_s = stats.get("Crafting") if isinstance(stats.get("Crafting"), dict) else {}
            crafting = int((craft_s or {}).get("Total") or 0)
            if pve or gathering or crafting:
                extra_stats += (
                    f"\n**PvE** `{pve:,}`  ·  **Gathering** `{gathering:,}`  ·  **Craft** `{crafting:,}`"
                ).replace(",", " ")
            guild_name = data.get("GuildName")
            if guild_name:
                extra_stats += f"\n**Guilde in-game** {guild_name}"
            if albion_id:
                try:
                    kills = await api.get_player_kills(albion_id, limit=1)
                    deaths = await api.get_player_deaths(albion_id, limit=1)
                except AlbionAPIError:
                    kills, deaths = [], []
                event = None
                if isinstance(kills, list) and kills:
                    event = kills[0]
                    who = "Killer"
                elif isinstance(deaths, list) and deaths:
                    event = deaths[0]
                    who = "Victim"
                else:
                    who = "Killer"
                if isinstance(event, dict):
                    eq = ((event.get(who) or {}).get("Equipment")) or {}
                    if isinstance(eq, dict):
                        portrait = character_render_url(eq)
                        weapon = _equip_token(eq.get("MainHand") if isinstance(eq.get("MainHand"), dict) else None)
                        armor = _equip_token(eq.get("Armor") if isinstance(eq.get("Armor"), dict) else None)
                        bits = [p.split("@")[0].split("?")[0] for p in (weapon, armor) if p]
                        if bits:
                            gear_line = " · ".join(bits)
    finally:
        await api.close()

    embed = discord.Embed(
        description=(
            f"-# PROFIL GUILDE\n"
            f"# {user.display_name}\n"
            f"{user.mention}\n\n"
            f"**Albion**  {albion_name or '*non renseigné — `/profil_pseudo`*'}\n"
            f"**Rang**  {rank}\n"
            f"**Style**  {gameplay}\n"
            f"**Onboarding**  règles {'✅' if rules_ok else '❌'}   ·   fiche {'✅' if profile_ok else '❌'}"
            f"{extra_stats}\n"
            f"{('**Stuff récent**  `' + gear_line + '`') if gear_line else ''}\n\n"
            f"## CONTRIBUTION\n"
            f"💰 **Dons**     {format_silver(donated)}\n"
            f"📅 **Ce mois**  {format_silver(donated_m)}\n"
            f"🎯 **Ordres**   {pts} pts  ·  mois {pts_m}\n"
            f"⚔️ **Fame**     {str(fame).replace(',', ' ') if False else f'{fame:,}'.replace(',', ' ')}"
        ),
        color=discord.Color.gold(),
    )
    if portrait:
        embed.set_image(url=portrait)
    if getattr(user, "display_avatar", None):
        embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Albion PPCF • Fort Sterling")
    return embed


async def apply_playstyle_role(guild: discord.Guild, member: discord.Member, key: str) -> None:
    """Un seul rôle de style à la fois (comme les boutons radio du serveur)."""

    wanted = find_role(guild, key)
    to_remove = []
    for other in PLAYSTYLE_ROLE_KEYS:
        role = find_role(guild, other)
        if role and role in member.roles and other != key:
            to_remove.append(role)
    try:
        if to_remove:
            await member.remove_roles(*to_remove, reason="Style de jeu")
        if wanted and wanted not in member.roles:
            await member.add_roles(wanted, reason="Style de jeu")
    except discord.HTTPException:
        LOGGER.warning("Impossible d'appliquer le rôle style %s à %s", key, member)


def _can_use_test_commands(member: discord.Member) -> bool:
    if settings.test_mode:
        return True
    return is_guild_master(member) or is_officer(member)


class RulesAcceptView(discord.ui.View):
    """Bouton permanent d'acceptation des règles."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="J'accepte les règles",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id=RULES_CUSTOM_ID,
    )
    async def accept_rules(self, interaction: discord.Interaction, _button: discord.ui.Button[Any]) -> None:
        await handle_accept_rules(interaction)


class ProfileOpenView(discord.ui.View):
    """Bouton permanent pour ouvrir le formulaire de profil."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Compléter mon profil",
        style=discord.ButtonStyle.primary,
        emoji="📋",
        custom_id=PROFILE_CUSTOM_ID,
    )
    async def open_profile(self, interaction: discord.Interaction, _button: discord.ui.Button[Any]) -> None:
        await interaction.response.send_message(
            embed=info_embed("Profil de guilde", "Choisis ton style de jeu :"),
            view=GameplaySelectView(),
            ephemeral=True,
        )


class GameplaySelect(discord.ui.Select["GameplaySelectView"]):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="Combattre d'autres joueurs (PvP)", value="pvp", emoji="⚔️"),
            discord.SelectOption(label="Affronter des monstres / Donjons (PvE)", value="pve", emoji="🛡️"),
            discord.SelectOption(label="Récolter des ressources (Gathering)", value="gathering", emoji="⛏️"),
            discord.SelectOption(label="Fabriquer et vendre (Craft / Économie)", value="craft", emoji="🔨"),
            discord.SelectOption(label="Je veux un peu de tout (Polyvalent)", value="polyvalent", emoji="🎲"),
        ]
        super().__init__(
            placeholder="Choisis un style…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="onboarding:gameplay_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        key = self.values[0]
        guild = interaction.guild
        user = interaction.user
        if guild and isinstance(user, discord.Member):
            await apply_playstyle_role(guild, user, key)
        await interaction.response.send_modal(AlbionNameModal(key))


class GameplaySelectView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(GameplaySelect())


class AlbionNameModal(discord.ui.Modal, title="Pseudo Albion"):
    albion_name = discord.ui.TextInput(
        label="Pseudo Albion",
        placeholder="Laisse vide si tu n'as pas encore le jeu",
        required=False,
        max_length=120,
    )

    def __init__(self, gameplay: str) -> None:
        super().__init__()
        self.gameplay = gameplay

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        key = self.gameplay if self.gameplay in GAMEPLAY_CHOICES else "polyvalent"
        member = interaction.user
        async with session_scope() as session:
            db_member = await get_or_create_member(
                session,
                discord_id=member.id,
                discord_name=member.display_name,
            )
            albion = str(self.albion_name).strip() or None
            db_member.albion_name = albion
            db_member.preferred_gameplay = key
            db_member.profile_completed = True
            rules_ok = db_member.rules_accepted

        validated = await maybe_validate_member(interaction, rules_ok=rules_ok, profile_ok=True)
        extra = "" if rules_ok else "\nIl te reste à accepter les règles dans #règles."
        if validated:
            extra = "\nTu es maintenant **Recrue**. Bienvenue !"
        await interaction.followup.send(
            embed=success_embed(
                "Profil enregistré",
                f"Style : **{GAMEPLAY_CHOICES[key]}**\nPseudo Albion : **{albion or 'non renseigné'}**{extra}",
            ),
            ephemeral=True,
        )


async def handle_accept_rules(interaction: discord.Interaction) -> None:
    member = interaction.user
    async with session_scope() as session:
        db_member = await get_or_create_member(
            session,
            discord_id=member.id,
            discord_name=member.display_name,
        )
        db_member.rules_accepted = True
        profile_ok = db_member.profile_completed

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    validated = await maybe_validate_member(interaction, rules_ok=True, profile_ok=profile_ok)
    extra = "" if profile_ok else "\nComplète encore ton profil via **Compléter mon profil**."
    if validated:
        extra = "\nTu es maintenant **Recrue**. Bienvenue !"
    await interaction.followup.send(
        embed=success_embed("Règles acceptées", f"Merci !{extra}"),
        ephemeral=True,
    )


async def maybe_validate_member(
    interaction: discord.Interaction,
    *,
    rules_ok: bool,
    profile_ok: bool,
) -> bool:
    """Passe Non vérifié → Recrue si les 2 étapes sont faites."""

    if not (rules_ok and profile_ok):
        return False
    guild = interaction.guild
    member = interaction.user
    if guild is None or not isinstance(member, discord.Member):
        if interaction.guild_id:
            guild = interaction.client.get_guild(interaction.guild_id)
        if guild is None:
            return False
        fetched = guild.get_member(member.id)
        if fetched is None:
            return False
        member = fetched

    unverified = find_role(guild, "unverified")
    recruit = find_role(guild, "recruit")
    try:
        if unverified and unverified in member.roles:
            await member.remove_roles(unverified, reason="Onboarding validé")
        if recruit and recruit not in member.roles:
            await member.add_roles(recruit, reason="Onboarding validé")
    except discord.Forbidden:
        LOGGER.warning("Permissions manquantes pour changer les rôles de %s", member)
    except discord.HTTPException:
        LOGGER.exception("Erreur Discord lors de la validation de %s", member)

    async with session_scope() as session:
        db_member = await get_or_create_member(
            session, discord_id=member.id, discord_name=member.display_name
        )
        db_member.current_rank = "recruit"

    arrival = find_channel(guild, "arrival_departure")
    if arrival is not None:
        await arrival.send(
            embed=success_embed(
                "Nouveau membre validé",
                f"🎉 {member.mention} a rejoint la guilde !",
            )
        )

    try:
        await member.send(
            embed=info_embed(
                "Bienvenue parmi les recrues",
                (
                    "Ton profil est validé. Commandes utiles :\n"
                    "• `/profil` — voir ton profil\n"
                    "• `/profil_pseudo` — mettre à jour ton pseudo Albion\n"
                    "• `/profil_role` — mettre à jour ton style de jeu\n"
                    "Ensuite, passe dans #rôles pour tes classes (Tank / DPS / Healer / Support)."
                ),
            )
        )
    except discord.Forbidden:
        pass
    return True


def build_rules_embed() -> discord.Embed:
    embed = discord.Embed(
        description=(
            "-# RÈGLEMENT PPCF\n"
            "## 📖  RÈGLES\n\n"
            "• **Respect** entre membres, zéro harcèlement.\n"
            "• Pas de spam, pas de pub hors guilde.\n"
            "• Utilise le **bon salon** pour le bon sujet.\n"
            "• **Tout don** (silver ou items) se déclare via un **ticket** dans #✉️ declaration. "
            "Pas de don « dans le vide ».\n"
            "• La guilde fonctionne à la **confiance**. Les promotions aussi : "
            "on avance selon l'activité et la parole donnée, pas selon le copinage.\n"
            "• Participe aux déploiements quand tu peux.\n"
            "• Ne divulgue pas les infos internes (sorties, coffre, tickets).\n"
            "• Signale un problème via le ticket **Problème**.\n"
            "• **Pas de furry** : aucun contenu / RP / avatar furry autorisé sur le serveur.\n\n"
            "Clique **J'accepte les règles** une fois que c'est lu."
        ),
        color=discord.Color.orange(),
    )
    embed.set_footer(text="Albion PPCF • Fort Sterling")
    return embed


def build_guide_embeds() -> list[discord.Embed]:
    color = discord.Color.dark_gold()
    e1 = discord.Embed(
        description=(
            "-# GUIDE NOUVEAU\n"
            "## 🎓  COMMENT FONCTIONNE LE SERVEUR\n\n"
            "Lis ce salon une fois, ça suffit pour tout le reste.\n\n"
            "1. Accepte les **règles**\n"
            "2. **Complète ton profil** (style + pseudo Albion)\n"
            "3. Prends tes **rôles** dans #🎭 rôles (style + Tank/DPS/Healer/Support)\n"
            "4. Ensuite tu peux tout utiliser : ordres, quêtes, sorties, banque, marché"
        ),
        color=color,
    )
    e2 = discord.Embed(
        description=(
            "## 🎯  ORDRES PRIORITAIRES\n\n"
            "Missions de guilde numérotées (#001…) dans #🎯 ordre-prioritaire.\n"
            "• Clique **Accepter** pour t'inscrire.\n"
            "• La barre avance toute seule (fame, silver déposé, items apportés) ou via **Progression**.\n"
            "• **Quota atteint** = ordre **réussi** + points.\n"
            "• **Délai dépassé** = ordre **échoué**, **aucun point**.\n"
            "• 24h après, l'ordre part dans #📜 ordres-passés.\n"
            "`/ordre_info` pour revoir une fiche."
        ),
        color=color,
    )
    e3 = discord.Embed(
        description=(
            "## 📋  QUÊTES\n\n"
            "Mini-sorties entre membres, max **3** joueurs, dans #📋 tableau-des-quêtes.\n"
            "`/quete` pour poster. **Participer** / **Terminer** (créateur seulement).\n"
            "Le message disparaît 6h après la fin."
        ),
        color=color,
    )
    e4 = discord.Embed(
        description=(
            "## 🐴  DÉPLOIEMENTS\n\n"
            "Sorties de guilde (ZvZ, donjon, gank…) dans #🐴 déploiement.\n"
            "Prends le rôle **🐴 déploiement** pour être ping.\n"
            "`/deployer` (officiers). Réponds ✅ / ⏳ / ❌ + ton rôle (Tank/DPS/Healer/Support).\n"
            "Rappel **en DM uniquement** 10 min avant, si tu es inscrit."
        ),
        color=color,
    )
    e5 = discord.Embed(
        description=(
            "## 💰  BANQUE & DONS\n\n"
            "Le coffre est dans #💰 trésorie (oui, sans « r »).\n"
            "**Tout don se déclare** avec un ticket **💰 Don** dans #✉️ declaration. "
            "Le Grand Trésorier est prévenu en DM.\n"
            "Historique : #📜 historique.\n"
            "Demandes de stuff : ticket **Craft** ou `/ressource_ajouter` (trésorier).\n\n"
            "On ne « balance » pas du silver en jeu sans ticket : la banque se base sur **ta déclaration**."
        ),
        color=color,
    )
    e6 = discord.Embed(
        description=(
            "## 🏅  PROMOTIONS & CONFIANCE\n\n"
            "Recrue → Chevalier → Officier… selon l'activité **et** la confiance.\n"
            "Pas de quota magique : si tu tiens parole (dons déclarés, ordres, sorties), ça se voit.\n"
            "Les promos sont affichées dans #🏅 promotion. `/promotion` / `/retrograder` (staff).\n\n"
            "## 🛒  MARCHÉ\n"
            "`/prix` `/historique_prix` `/watchlist_ajouter` dans #🛒 commandes-marché. "
            "Alertes auto dans #🚨 alertes-prix.\n\n"
            "## 💀  KILLBOARD\n"
            "Tes kills/morts de guilde dans #💀 champ-de-bataille — il te faut `/profil_pseudo`.\n\n"
            "`/aide` pour la liste des commandes."
        ),
        color=color,
    )
    for embed in (e1, e2, e3, e4, e5, e6):
        embed.set_footer(text="Albion PPCF • Fort Sterling")
    return [e1, e2, e3, e4, e5, e6]


def build_welcome_embed(member: discord.Member | discord.User) -> discord.Embed:
    embed = success_embed(
        f"🎉 Bienvenue {member.display_name} !",
        (
            "Lis les **règles** puis clique **Compléter mon profil** "
            "(ou tape `/completer_profil` si le bouton ne répond pas).\n"
            "Les deux étapes sont nécessaires pour passer Recrue."
        ),
    )
    avatar = getattr(member, "display_avatar", None)
    if avatar is not None:
        embed.set_thumbnail(url=avatar.url)
    return embed


class Onboarding(commands.Cog):
    """Arrivée, règles, formulaire et commandes de test."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(RulesAcceptView())
        self.bot.add_view(ProfileOpenView())
        self.bot.add_view(GameplaySelectView())

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        await self._process_join(member)

    async def _process_join(self, member: discord.Member) -> None:
        guild = member.guild
        unverified = find_role(guild, "unverified")
        if unverified is not None:
            try:
                await member.add_roles(unverified, reason="Nouvel arrivant")
            except discord.HTTPException:
                LOGGER.exception("Impossible d'attribuer Non vérifié à %s", member)

        async with session_scope() as session:
            db_member = await get_or_create_member(
                session, discord_id=member.id, discord_name=member.display_name
            )
            db_member.joined_at = db_member.joined_at or utcnow()
            db_member.left_at = None
            db_member.current_rank = "unverified"
            db_member.rules_accepted = False
            db_member.profile_completed = False

        arrival = find_channel(guild, "arrival_departure")
        if arrival is not None:
            await arrival.send(
                content=member.mention,
                embed=build_welcome_embed(member),
                view=ProfileOpenView(),
            )

        try:
            await member.send(
                embed=build_welcome_embed(member),
                view=ProfileOpenView(),
            )
        except discord.Forbidden:
            LOGGER.info("DM fermés pour %s", member.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.bot:
            return
        days = 0
        async with session_scope() as session:
            db_member = await get_or_create_member(
                session, discord_id=member.id, discord_name=member.display_name
            )
            db_member.left_at = utcnow()
            if db_member.joined_at:
                days = max(0, (utcnow() - db_member.joined_at).days)
            rank = db_member.current_rank
            donated = 0
            points = 0

        arrival = find_channel(member.guild, "arrival_departure")
        if arrival is None:
            return
        embed = warning_embed(
            f"👋 {member.display_name} a quitté la guilde",
            f"Ancienneté : **{days}** jours\nRang : **{rank}**\nDons : **{donated}** silver\nPoints ordres : **{points}**",
        )
        if member.display_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)
        await arrival.send(embed=embed)

    @app_commands.command(name="setup_onboarding", description="Poste les embeds #règles et #guide-nouveau.")
    @app_commands.guild_only()
    async def setup_onboarding(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not _can_use_test_commands(interaction.user):
            await interaction.response.send_message("Permission insuffisante.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        assert guild is not None
        rules_ch = find_channel(guild, "rules")
        guide_ch = find_channel(guild, "new_guide")
        posted: list[str] = []
        errors: list[str] = []
        if rules_ch:
            await rules_ch.send(embed=build_rules_embed(), view=RulesAcceptView())
            posted.append(f"règles → {rules_ch.mention}")
        else:
            errors.append("salon **règles** introuvable")
        if guide_ch is None:
            category = rules_ch.category if rules_ch else None
            try:
                guide_ch = await guild.create_text_channel(
                    CHANNEL_NAMES["new_guide"],
                    category=category,
                    topic="Guide nouveau membre PPCF",
                    reason="setup_onboarding : salon guide manquant",
                )
                posted.append(f"salon créé → {guide_ch.mention}")
            except discord.HTTPException as exc:
                errors.append(f"impossible de créer le guide ({exc})")
        if guide_ch:
            sent = 0
            for embed in build_guide_embeds():
                try:
                    await guide_ch.send(embed=embed)
                    sent += 1
                except discord.HTTPException:
                    LOGGER.exception("Envoi d'un embed guide échoué")
            if sent:
                posted.append(f"guide ({sent} embeds) → {guide_ch.mention}")
            else:
                errors.append(f"aucun embed posté dans {guide_ch.mention}")
        arrival = find_channel(guild, "arrival_departure")
        if arrival:
            await arrival.send(
                embed=build_welcome_embed(interaction.user),
                view=ProfileOpenView(),
            )
            posted.append(arrival.mention)
        if not posted:
            await interaction.followup.send(
                embed=error_embed("Salons introuvables", f"Attendu : {CHANNEL_NAMES['rules']} et {CHANNEL_NAMES['new_guide']}"),
                ephemeral=True,
            )
            return
        detail = "\n".join(f"• {line}" for line in posted) or "*rien posté*"
        if errors:
            detail += "\n\n⚠️ " + "\n".join(errors)
        await interaction.followup.send(embed=success_embed("Onboarding", detail), ephemeral=True)

    @app_commands.command(name="completer_profil", description="Ouvre le formulaire de profil (même action que le bouton).")
    async def completer_profil(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=info_embed("Profil de guilde", "Choisis ton style de jeu :"),
            view=GameplaySelectView(),
            ephemeral=True,
        )

    @app_commands.command(name="profil", description="Fiche profil (dons, points, portrait Albion équipé).")
    @app_commands.describe(membre="Laisse vide = toi")
    async def profil(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        await interaction.response.defer(ephemeral=False)
        target = membre or interaction.user
        embed = await build_member_profile_embed(target)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="profil_pseudo", description="Met à jour ton pseudo Albion.")
    @app_commands.describe(pseudo="Pseudo in-game (vide pour effacer)")
    async def profil_pseudo(self, interaction: discord.Interaction, pseudo: str | None = None) -> None:
        async with session_scope() as session:
            member = await get_or_create_member(
                session, discord_id=interaction.user.id, discord_name=interaction.user.display_name
            )
            member.albion_name = (pseudo or "").strip() or None
            member.albion_player_id = None
        await interaction.response.send_message(
            embed=success_embed("Pseudo mis à jour", pseudo or "effacé"),
            ephemeral=True,
        )

    @app_commands.command(name="profil_role", description="Met à jour ton style de gameplay.")
    @app_commands.describe(style="pvp, pve, gathering, craft ou polyvalent")
    @app_commands.choices(
        style=[
            app_commands.Choice(name=label, value=key) for key, label in GAMEPLAY_CHOICES.items()
        ]
    )
    async def profil_role(self, interaction: discord.Interaction, style: app_commands.Choice[str]) -> None:
        async with session_scope() as session:
            member = await get_or_create_member(
                session, discord_id=interaction.user.id, discord_name=interaction.user.display_name
            )
            member.preferred_gameplay = style.value
            member.profile_completed = True
        if isinstance(interaction.user, discord.Member) and interaction.guild:
            await apply_playstyle_role(interaction.guild, interaction.user, style.value)
        await interaction.response.send_message(
            embed=success_embed("Style mis à jour", GAMEPLAY_CHOICES[style.value]),
            ephemeral=True,
        )

    @app_commands.command(name="test_welcome", description="[TEST] Simule ton arrivée (bienvenue + Non vérifié).")
    @app_commands.guild_only()
    async def test_welcome(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not _can_use_test_commands(interaction.user):
            await interaction.response.send_message("Mode test désactivé ou permission insuffisante.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self._process_join(interaction.user)
        await interaction.followup.send(embed=success_embed("Simulation OK", "Message de bienvenue posté."), ephemeral=True)

    @app_commands.command(name="test_reset_profil", description="[TEST] Remet ton onboarding à zéro.")
    @app_commands.guild_only()
    async def test_reset_profil(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not _can_use_test_commands(interaction.user):
            await interaction.response.send_message("Mode test désactivé ou permission insuffisante.", ephemeral=True)
            return
        member = interaction.user
        async with session_scope() as session:
            db_member = await get_or_create_member(
                session, discord_id=member.id, discord_name=member.display_name
            )
            db_member.rules_accepted = False
            db_member.profile_completed = False
            db_member.current_rank = "unverified"
            db_member.preferred_gameplay = None
        recruit = find_role(member.guild, "recruit")
        unverified = find_role(member.guild, "unverified")
        try:
            if recruit and recruit in member.roles:
                await member.remove_roles(recruit, reason="Reset test onboarding")
            if unverified and unverified not in member.roles:
                await member.add_roles(unverified, reason="Reset test onboarding")
        except discord.HTTPException:
            LOGGER.exception("Reset rôles impossible")
        await interaction.response.send_message(
            embed=warning_embed("Profil reset", "Tu es de nouveau Non vérifié. Refais règles + formulaire."),
            ephemeral=True,
        )

    @app_commands.command(name="test_validation", description="[TEST] Force la validation Recrue sur toi.")
    @app_commands.guild_only()
    async def test_validation(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not _can_use_test_commands(interaction.user):
            await interaction.response.send_message("Mode test désactivé ou permission insuffisante.", ephemeral=True)
            return
        async with session_scope() as session:
            db_member = await get_or_create_member(
                session, discord_id=interaction.user.id, discord_name=interaction.user.display_name
            )
            db_member.rules_accepted = True
            db_member.profile_completed = True
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        await maybe_validate_member(interaction, rules_ok=True, profile_ok=True)
        await interaction.followup.send(embed=success_embed("Forcé Recrue"), ephemeral=True)

    @app_commands.command(name="test_statut", description="[TEST] Affiche le mode test et tes flags onboarding.")
    async def test_statut(self, interaction: discord.Interaction) -> None:
        async with session_scope() as session:
            member = await get_or_create_member(
                session, discord_id=interaction.user.id, discord_name=interaction.user.display_name
            )
            embed = info_embed(
                "Statut test",
                (
                    f"TEST_MODE : **{settings.test_mode}**\n"
                    f"Règles : **{member.rules_accepted}**\n"
                    f"Profil : **{member.profile_completed}**\n"
                    f"Rang DB : **{member.current_rank}**"
                ),
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Onboarding(bot))
