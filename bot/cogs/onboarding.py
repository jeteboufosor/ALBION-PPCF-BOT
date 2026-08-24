"""Phase 2 — Onboarding: règles, formulaire profil, validation auto.

Workflow:
1. Arrivée → rôle Non vérifié + bienvenue + bouton profil
2. Accepter les règles + remplir le formulaire
3. Validation → Recrue + annonce + DM commandes utiles
"""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import CHANNEL_NAMES, settings
from bot.database.crud import get_or_create_member
from bot.database.engine import session_scope
from bot.database.models import utcnow
from bot.utils.embeds import error_embed, info_embed, success_embed, warning_embed
from bot.utils.permissions import find_channel, find_role, is_guild_master, is_officer

LOGGER = logging.getLogger(__name__)

GAMEPLAY_CHOICES: dict[str, str] = {
    "pvp": "⚔️ Combattre d'autres joueurs (PvP)",
    "pve": "🛡️ Affronter des monstres / Donjons (PvE)",
    "gathering": "⛏️ Récolter des ressources (Gathering)",
    "craft": "🔨 Fabriquer et vendre (Craft / Économie)",
    "polyvalent": "🎲 Je veux un peu de tout (Polyvalent)",
}

RULES_CUSTOM_ID = "onboarding:accept_rules"
PROFILE_CUSTOM_ID = "onboarding:open_profile"


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
                    "Ensuite, passe dans #rôles pour choisir Tank / DPS / Healer / Support."
                ),
            )
        )
    except discord.Forbidden:
        pass
    return True


def build_rules_embed() -> discord.Embed:
    embed = info_embed(
        "📖 Règles de la guilde",
        "Lis attentivement puis clique sur **J'accepte les règles**.",
    )
    embed.add_field(
        name="Règles",
        value=(
            "• Respect entre membres obligatoire\n"
            "• Pas de spam / pas de pub externe\n"
            "• Utiliser les bons salons pour les bons sujets\n"
            "• Signaler tout problème via #déclaration\n"
            "• Participer aux déploiements dans la mesure du possible\n"
            "• Ne pas trahir les infos internes à la guilde\n"
            "• Contribuer selon ses moyens (temps, ressources, silver)"
        ),
        inline=False,
    )
    return embed


def build_guide_embed() -> discord.Embed:
    embed = info_embed(
        "🎓 Guide nouveau membre",
        "Voici comment fonctionne le serveur.",
    )
    embed.add_field(
        name="Salons",
        value=(
            "❗ **Important** : règles, guide, rôles, leaderboard, ordres\n"
            "🔒 **Officier** : gestion, alertes, backups\n"
            "🏦 **Banque** : trésorerie, historique, déclaration\n"
            "🍺 **Taverne** : général, quêtes, LFG\n"
            "⚔️ **Caserne** : déploiements, promotions, killboard\n"
            "📊 **Marché** : prix, alertes, craft"
        ),
        inline=False,
    )
    embed.add_field(
        name="Systèmes",
        value=(
            "• **Ordres prioritaires** : participe dans #ordre-prioritaire\n"
            "• **Déclaration** : tickets via les boutons de #declaration\n"
            "• **Déploiements** : inscris-toi dans #déploiement\n"
            "• **Marché** : `/prix` dans #commandes-marché\n"
            "• **Contribution** : Recrue → Chevalier selon activité"
        ),
        inline=False,
    )
    embed.add_field(
        name="Commandes principales",
        value="`/profil` `/profil_pseudo` `/profil_role` `/setup` `/ping`",
        inline=False,
    )
    return embed


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
        if rules_ch:
            await rules_ch.send(embed=build_rules_embed(), view=RulesAcceptView())
            posted.append(rules_ch.mention)
        if guide_ch:
            await guide_ch.send(embed=build_guide_embed())
            posted.append(guide_ch.mention)
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
        await interaction.followup.send(
            embed=success_embed("Onboarding posté", "Salons : " + ", ".join(posted)),
            ephemeral=True,
        )

    @app_commands.command(name="completer_profil", description="Ouvre le formulaire de profil (même action que le bouton).")
    async def completer_profil(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ProfileModal())

    @app_commands.command(name="profil", description="Affiche ton profil de guilde.")
    async def profil(self, interaction: discord.Interaction) -> None:
        async with session_scope() as session:
            member = await get_or_create_member(
                session, discord_id=interaction.user.id, discord_name=interaction.user.display_name
            )
            gameplay = GAMEPLAY_CHOICES.get(member.preferred_gameplay or "", member.preferred_gameplay or "—")
            embed = info_embed(f"Profil — {interaction.user.display_name}")
            embed.add_field(name="Pseudo Albion", value=member.albion_name or "non renseigné", inline=True)
            embed.add_field(name="Rang", value=member.current_rank, inline=True)
            embed.add_field(name="Style", value=gameplay, inline=False)
            embed.add_field(name="Règles", value="✅" if member.rules_accepted else "❌", inline=True)
            embed.add_field(name="Profil", value="✅" if member.profile_completed else "❌", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="profil_pseudo", description="Met à jour ton pseudo Albion.")
    @app_commands.describe(pseudo="Pseudo in-game (vide pour effacer)")
    async def profil_pseudo(self, interaction: discord.Interaction, pseudo: str | None = None) -> None:
        async with session_scope() as session:
            member = await get_or_create_member(
                session, discord_id=interaction.user.id, discord_name=interaction.user.display_name
            )
            member.albion_name = (pseudo or "").strip() or None
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
