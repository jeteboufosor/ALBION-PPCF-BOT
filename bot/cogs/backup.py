"""Phase 7 — Backup SQLite / PostgreSQL."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import BACKUP_DIR, settings
from bot.database.engine import DATABASE_URL, IS_POSTGRES, IS_SQLITE
from bot.utils.embeds import error_embed, info_embed, success_embed
from bot.utils.permissions import find_channel, is_guild_master

BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _can_backup(member: discord.Member) -> bool:
    return settings.test_mode or is_guild_master(member)


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d_%H-%M")


async def create_backup_bytes() -> tuple[str, bytes]:
    name = f"backup_{_stamp()}.zip"
    buf = io.BytesIO()
    meta = {
        "type": "postgresql" if IS_POSTGRES else "sqlite",
        "created_at": datetime.now(UTC).isoformat(),
        "database_url_scheme": DATABASE_URL.split(":")[0],
    }
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("metadata.json", json.dumps(meta, indent=2))
        zf.writestr("config_snapshot.json", json.dumps({"guild_id": settings.guild_id}, indent=2))
        if IS_SQLITE:
            raw = DATABASE_URL.replace("sqlite+aiosqlite:///", "")
            path = Path(raw)
            if path.exists():
                zf.write(path, "data.db")
            else:
                zf.writestr("data.db", b"")
        else:
            zf.writestr(
                "dump.sql",
                "-- Dump logique : utilise pg_dump côté Railway si besoin d'un SQL complet.\n"
                f"-- DATABASE={DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else 'postgres'}\n",
            )
    return name, buf.getvalue()


async def send_backup(bot: commands.Bot, guild: discord.Guild, *, author: discord.Member | None = None) -> discord.Message | None:
    channel = find_channel(guild, "sql_backup")
    if channel is None:
        return None
    filename, payload = await create_backup_bytes()
    path = BACKUP_DIR / filename
    path.write_bytes(payload)
    # garde 30 fichiers
    old = sorted(BACKUP_DIR.glob("backup_*.zip"))
    for stale in old[:-30]:
        stale.unlink(missing_ok=True)
    who = author.mention if author else "auto 04h"
    msg = await channel.send(
        embed=success_embed("💾 Backup", f"{filename}\n{len(payload)/1024:.1f} Ko\npar {who}"),
        file=discord.File(io.BytesIO(payload), filename=filename),
    )
    return msg


class Backup(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="save", description="Backup manuel immédiat.")
    @app_commands.guild_only()
    async def save(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not _can_backup(interaction.user):
            await interaction.followup.send("Maître de Guilde uniquement (ou mode test).", ephemeral=True)
            return
        msg = await send_backup(self.bot, interaction.guild, author=interaction.user)  # type: ignore[arg-type]
        if msg is None:
            await interaction.followup.send(embed=error_embed("Salon #backup-sql introuvable"), ephemeral=True)
            return
        await interaction.followup.send(embed=success_embed("Backup envoyé", msg.jump_url), ephemeral=True)

    @app_commands.command(name="backup_info", description="Infos backups.")
    @app_commands.guild_only()
    async def backup_info(self, interaction: discord.Interaction) -> None:
        files = sorted(BACKUP_DIR.glob("backup_*.zip"))
        last = files[-1].name if files else "aucun"
        size = 0
        if IS_SQLITE:
            raw = DATABASE_URL.replace("sqlite+aiosqlite:///", "")
            p = Path(raw)
            size = p.stat().st_size if p.exists() else 0
        await interaction.response.send_message(
            embed=info_embed(
                "💾 Backup",
                f"Dernier : **{last}**\nConservés : **{len(files)}**/30\nDB : {'PostgreSQL' if IS_POSTGRES else 'SQLite'} ({size} o)",
            ),
            ephemeral=True,
        )

    @app_commands.command(name="load", description="Restauration (ZIP) — confirmation requise.")
    @app_commands.guild_only()
    async def load(self, interaction: discord.Interaction, fichier: discord.Attachment) -> None:
        if not isinstance(interaction.user, discord.Member) or not _can_backup(interaction.user):
            await interaction.response.send_message("Permission insuffisante.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=info_embed(
                "Restauration",
                "Un backup de sécurité est créé d'abord. Envoie `/save` puis contacte un admin pour appliquer le ZIP "
                f"**{fichier.filename}** (restauration auto risquée en prod PostgreSQL).",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Backup(bot))
