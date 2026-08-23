"""Modèles SQLAlchemy 2.0 du bot de guilde Albion Online.

Le schéma couvre toutes les fonctionnalités prévues par les 7 phases.
Les statuts/types sont stockés en chaînes pour rester simples et compatibles
SQLite/PostgreSQL sans migration complexe au début du projet.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def utcnow() -> datetime:
    """Date UTC timezone-aware pour les valeurs par défaut."""

    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base déclarative SQLAlchemy."""

    type_annotation_map = {dict[str, Any]: MutableDict.as_mutable(JSON().with_variant(JSONB, "postgresql"))}


class TimestampMixin:
    """Colonnes d'audit communes."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Member(Base, TimestampMixin):
    """Membre Discord relié à son profil Albion."""

    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    discord_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    discord_name: Mapped[str] = mapped_column(String(120), nullable=False)
    albion_player_id: Mapped[str | None] = mapped_column(String(80), index=True)
    albion_name: Mapped[str | None] = mapped_column(String(120), index=True)
    preferred_gameplay: Mapped[str | None] = mapped_column(String(40))
    current_rank: Mapped[str] = mapped_column(String(40), default="unverified", nullable=False)
    rules_accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    profile_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    class_roles: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)

    order_participations: Mapped[list[OrderParticipant]] = relationship(back_populates="member", cascade="all, delete-orphan")
    quest_participations: Mapped[list[QuestParticipant]] = relationship(back_populates="member", cascade="all, delete-orphan")
    contribution_score: Mapped[ContributionScore | None] = relationship(back_populates="member", cascade="all, delete-orphan")
    donations: Mapped[list[GuildDonation]] = relationship(back_populates="member")
    debts: Mapped[list[Debt]] = relationship(back_populates="member")
    tickets: Mapped[list[Ticket]] = relationship(back_populates="member")
    deployment_responses: Mapped[list[DeploymentResponse]] = relationship(back_populates="member", cascade="all, delete-orphan")


class Order(Base, TimestampMixin):
    """Ordre prioritaire numéroté (#001, #002...)."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)  # low, medium, high, critical
    objective_type: Mapped[str] = mapped_column(String(40), nullable=False)
    objective_item_name: Mapped[str | None] = mapped_column(String(160))
    target_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    current_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True, nullable=False)
    reward_type: Mapped[str] = mapped_column(String(40), nullable=False)
    reward_winner: Mapped[str | None] = mapped_column(Text)
    reward_gold: Mapped[str | None] = mapped_column(Text)
    reward_silver: Mapped[str | None] = mapped_column(Text)
    reward_bronze: Mapped[str | None] = mapped_column(Text)
    reward_others: Mapped[str | None] = mapped_column(Text)
    points_value: Mapped[int] = mapped_column(Integer, nullable=False)
    creator_discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cancelled_by_discord_id: Mapped[int | None] = mapped_column(BigInteger)
    completed_by_discord_id: Mapped[int | None] = mapped_column(BigInteger)
    close_reason: Mapped[str | None] = mapped_column(String(40))
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    participants: Mapped[list[OrderParticipant]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderParticipant(Base, TimestampMixin):
    """Participation et contribution d'un membre à un ordre."""

    __tablename__ = "order_participants"
    __table_args__ = (UniqueConstraint("order_id", "member_id", name="uq_order_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    contribution_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    contribution_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    points_awarded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    order: Mapped[Order] = relationship(back_populates="participants")
    member: Mapped[Member] = relationship(back_populates="order_participations")


class Quest(Base, TimestampMixin):
    """Mini-ordre du tableau des quêtes."""

    __tablename__ = "quests"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reward: Mapped[str | None] = mapped_column(Text)
    creator_member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    max_participants: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True, nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delete_after_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    creator: Mapped[Member] = relationship(foreign_keys=[creator_member_id])
    participants: Mapped[list[QuestParticipant]] = relationship(back_populates="quest", cascade="all, delete-orphan")


class QuestParticipant(Base, TimestampMixin):
    """Participant d'une quête."""

    __tablename__ = "quest_participants"
    __table_args__ = (UniqueConstraint("quest_id", "member_id", name="uq_quest_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quest_id: Mapped[int] = mapped_column(ForeignKey("quests.id", ondelete="CASCADE"), nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)

    quest: Mapped[Quest] = relationship(back_populates="participants")
    member: Mapped[Member] = relationship(back_populates="quest_participations")


class ContributionScore(Base, TimestampMixin):
    """Scores leaderboard all-time et mensuels."""

    __tablename__ = "contribution_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), unique=True, nullable=False)
    order_points_all_time: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    order_points_monthly: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_silver_donated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_fame: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    monthly_period: Mapped[str] = mapped_column(String(7), default="", nullable=False)  # YYYY-MM

    member: Mapped[Member] = relationship(back_populates="contribution_score")


class GuildDonation(Base, TimestampMixin):
    """Don validé via ticket/déclaration."""

    __tablename__ = "guild_donations"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    donation_type: Mapped[str] = mapped_column(String(20), nullable=False)  # silver, item
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    item_name: Mapped[str | None] = mapped_column(String(180))
    note: Mapped[str | None] = mapped_column(Text)
    approved_by_discord_id: Mapped[int | None] = mapped_column(BigInteger)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"))

    member: Mapped[Member | None] = relationship(back_populates="donations")


class TreasuryTransaction(Base, TimestampMixin):
    """Historique financier: dépôts, retraits, ajustements."""

    __tablename__ = "treasury_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    author_discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    donation_id: Mapped[int | None] = mapped_column(ForeignKey("guild_donations.id", ondelete="SET NULL"))


class TreasuryState(Base, TimestampMixin):
    """État courant de la trésorerie. Une ligne singleton."""

    __tablename__ = "treasury_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    current_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_deposited: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_withdrawn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    treasury_message_id: Mapped[int | None] = mapped_column(BigInteger)


class Debt(Base, TimestampMixin):
    """Dette d'un membre envers la guilde."""

    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True, nullable=False)
    created_by_discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    repaid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    member: Mapped[Member] = relationship(back_populates="debts")


class ResourceRequest(Base, TimestampMixin):
    """Demande de ressource/craft visible dans la trésorerie."""

    __tablename__ = "resource_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_name: Mapped[str] = mapped_column(String(180), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    original_quantity: Mapped[int | None] = mapped_column(Integer)
    requester_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"))
    reason: Mapped[str | None] = mapped_column(Text)
    urgency: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="open", index=True, nullable=False)
    created_by_discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Ticket(Base, TimestampMixin):
    """Ticket privé créé depuis #declaration."""

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_number: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    ticket_type: Mapped[str] = mapped_column(String(40), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(180))
    description: Mapped[str | None] = mapped_column(Text)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    warned_inactive_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_discord_id: Mapped[int | None] = mapped_column(BigInteger)
    archive_message_id: Mapped[int | None] = mapped_column(BigInteger)

    member: Mapped[Member] = relationship(back_populates="tickets")


class Deployment(Base, TimestampMixin):
    """Évènement de déploiement."""

    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    required_stuff: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_slots: Mapped[int | None] = mapped_column(Integer)
    creator_discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(30), default="scheduled", index=True, nullable=False)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    responses: Mapped[list[DeploymentResponse]] = relationship(back_populates="deployment", cascade="all, delete-orphan")


class DeploymentResponse(Base, TimestampMixin):
    """Réponse RSVP à un déploiement."""

    __tablename__ = "deployment_responses"
    __table_args__ = (UniqueConstraint("deployment_id", "member_id", name="uq_deployment_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    deployment_id: Mapped[int] = mapped_column(ForeignKey("deployments.id", ondelete="CASCADE"), nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    response: Mapped[str] = mapped_column(String(20), nullable=False)  # yes, maybe, no
    class_role: Mapped[str | None] = mapped_column(String(30))
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    deployment: Mapped[Deployment] = relationship(back_populates="responses")
    member: Mapped[Member] = relationship(back_populates="deployment_responses")


class Promotion(Base, TimestampMixin):
    """Historique de promotion/rétrogradation."""

    __tablename__ = "promotions"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    old_rank: Mapped[str] = mapped_column(String(40), nullable=False)
    new_rank: Mapped[str] = mapped_column(String(40), nullable=False)
    promoted_by_discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


class KillEvent(Base, TimestampMixin):
    """Évènement killboard Albion impliquant la guilde."""

    __tablename__ = "kill_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    albion_event_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)  # kill, death
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"))
    member_name: Mapped[str] = mapped_column(String(120), nullable=False)
    opponent_name: Mapped[str] = mapped_column(String(120), nullable=False)
    opponent_guild: Mapped[str | None] = mapped_column(String(160))
    fame: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    zone_name: Mapped[str | None] = mapped_column(String(160))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    equipment: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    posted_message_id: Mapped[int | None] = mapped_column(BigInteger)


class MarketWatch(Base, TimestampMixin):
    """Alerte de prix marché configurée par un membre."""

    __tablename__ = "market_watches"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"))
    item_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    item_name: Mapped[str] = mapped_column(String(180), nullable=False)
    city: Mapped[str] = mapped_column(String(80), default="Fort Sterling", nullable=False)
    low_threshold: Mapped[int | None] = mapped_column(Integer)
    high_threshold: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MarketPriceSnapshot(Base, TimestampMixin):
    """Snapshot historique d'un prix marché."""

    __tablename__ = "market_price_snapshots"
    __table_args__ = (Index("ix_market_item_city_time", "item_id", "city", "sampled_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[str] = mapped_column(String(120), nullable=False)
    item_name: Mapped[str | None] = mapped_column(String(180))
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    sell_price_min: Mapped[int | None] = mapped_column(Integer)
    sell_price_max: Mapped[int | None] = mapped_column(Integer)
    buy_price_min: Mapped[int | None] = mapped_column(Integer)
    buy_price_max: Mapped[int | None] = mapped_column(Integer)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)


class FameSnapshot(Base, TimestampMixin):
    """Snapshot fame joueur pour calculer les progressions automatiques."""

    __tablename__ = "fame_snapshots"
    __table_args__ = (Index("ix_fame_member_time", "member_id", "sampled_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    pve_fame: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pvp_fame: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gathering_fame: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    crafting_fame: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_fame: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)


class BackupLog(Base, TimestampMixin):
    """Journal des backups automatiques/manuels."""

    __tablename__ = "backup_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    backup_type: Mapped[str] = mapped_column(String(20), nullable=False)  # auto, manual, safety
    database_type: Mapped[str] = mapped_column(String(20), nullable=False)  # sqlite, postgresql
    filename: Mapped[str] = mapped_column(String(260), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_by_discord_id: Mapped[int | None] = mapped_column(BigInteger)
    error_message: Mapped[str | None] = mapped_column(Text)
    posted_message_id: Mapped[int | None] = mapped_column(BigInteger)


class BotHealthStat(Base, TimestampMixin):
    """Métriques pour alertes et rapport hebdomadaire."""

    __tablename__ = "bot_health_stats"

    id: Mapped[int] = mapped_column(primary_key=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    commands_executed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    backups_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_orders_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uptime_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    db_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
