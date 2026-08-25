"""Point d'entrée minimal du bot Discord.

Phase 1: connexion, initialisation DB, chargement dynamique des cogs.
Les fonctionnalités Discord complètes seront ajoutées phase par phase.
"""

from __future__ import annotations

import asyncio
import logging
import pkgutil
import sys
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import settings
from bot.database.engine import dispose_engine, init_db
from bot.tasks.scheduler import start_scheduler, stop_scheduler


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stdout,
    )


class AlbionGuildBot(commands.Bot):
    """Bot principal avec setup async."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.dm_messages = True
        super().__init__(command_prefix=settings.command_prefix, intents=intents)
        self.started_at = datetime.now(UTC)
        self.logger = logging.getLogger("bot")

    async def setup_hook(self) -> None:
        """Initialise la DB et charge les cogs avant connexion complète."""

        await init_db()
        await self._load_available_cogs()
        start_scheduler(self)
        self.tree.on_error = self.on_app_command_error

        if settings.sync_commands_on_start:
            try:
                if settings.guild_id:
                    guild = discord.Object(id=settings.guild_id)
                    self.tree.copy_global_to(guild=guild)
                    synced = await self.tree.sync(guild=guild)
                    self.logger.info(
                        "%s commande(s) slash synchronisée(s) sur la guilde %s: %s",
                        len(synced),
                        settings.guild_id,
                        ", ".join(f"/{command.name}" for command in synced) or "aucune",
                    )
                else:
                    synced = await self.tree.sync()
                    self.logger.info(
                        "%s commande(s) slash globale(s) synchronisée(s): %s",
                        len(synced),
                        ", ".join(f"/{command.name}" for command in synced) or "aucune",
                    )
                if not synced:
                    self.logger.warning(
                        "Aucune commande à synchroniser: vérifiez que les cogs exposant des slash commands sont bien chargés."
                    )
            except Exception:
                self.logger.exception(
                    "Sync des commandes échouée — le bot continue sans sync. "
                    "Vérifiez les descriptions (max 100 chars) et les noms de commandes."
                )

    async def _load_available_cogs(self) -> None:
        """Charge tous les modules bot.cogs.* qui exposent setup(bot)."""

        import bot.cogs as cogs_package

        for module_info in pkgutil.iter_modules(cogs_package.__path__):
            if module_info.name.startswith("_"):
                continue
            extension = f"bot.cogs.{module_info.name}"
            try:
                await self.load_extension(extension)
                self.logger.info("Cog chargé: %s", extension)
            except commands.NoEntryPointError:
                self.logger.warning("Cog ignoré (setup absent): %s", extension)
            except Exception:
                self.logger.exception("Erreur chargement cog: %s", extension)

    async def on_ready(self) -> None:
        guilds = ", ".join(guild.name for guild in self.guilds) or "aucune guilde"
        self.logger.info("Connecté en tant que %s (%s) | Guildes: %s", self.user, self.user.id if self.user else "?", guilds)

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        """Évite le toast rouge si la commande a déjà répondu / est trop longue."""

        original = getattr(error, "original", error)
        if isinstance(original, discord.errors.NotFound):
            return
        if isinstance(original, discord.HTTPException) and getattr(original, "code", None) == 40060:
            return
        self.logger.exception("Erreur commande /%s", getattr(interaction.command, "name", "?"))
        msg = "Une erreur est survenue. Réessaie dans un instant."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass

    async def close(self) -> None:
        stop_scheduler()
        await super().close()
        await dispose_engine()


async def run_bot() -> None:
    configure_logging()
    if not settings.discord_token:
        raise RuntimeError("DISCORD_TOKEN manquant. Configure-le dans Railway (Variables).")

    bot = AlbionGuildBot()
    async with bot:
        await bot.start(settings.discord_token)


def main() -> None:
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
