"""Shared SQLModel schema for the metadata store.

Datetime columns are declared with an explicit sa_type=DateTime: this app stores naive local
times, and newer sqlmodel releases (0.0.48+) otherwise reject any datetime without a timezone.

Used both by the synthetic data generator (data/generate_synthetic_data.py) and the
runtime retrieval/personalization code (app/retrieval/metadata_search.py,
app/personalization/*), so there is exactly one definition of the schema.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index
from sqlmodel import Field, SQLModel


class FileRecord(SQLModel, table=True):
    __tablename__ = "files"

    id: int | None = Field(default=None, primary_key=True)
    filename: str
    path: str
    file_type: str = Field(index=True)
    size_bytes: int
    created_at: datetime = Field(sa_type=DateTime)
    modified_at: datetime = Field(sa_type=DateTime)
    topic_cluster: str = Field(index=True)
    extracted_text: str = ""


class UserRecord(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    persona_key: str = Field(index=True)


class AccessEvent(SQLModel, table=True):
    __tablename__ = "access_log"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    file_id: int = Field(foreign_key="files.id", index=True)
    action: str  # "open" | "edit" | "search"
    timestamp: datetime = Field(index=True, sa_type=DateTime)
    session_id: str = Field(index=True)


class FeedbackEvent(SQLModel, table=True):
    """Implicit/explicit feedback written back by the UI (thumbs up/down, "I opened this").
    Consumed by personalization/retrain.py in the extended-scope phase."""

    __tablename__ = "feedback_log"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    file_id: int = Field(foreign_key="files.id", index=True)
    query: str
    signal: str  # "thumbs_up" | "thumbs_down" | "opened"
    timestamp: datetime = Field(index=True, sa_type=DateTime)


class IndexState(SQLModel, table=True):
    """Where each file is in the background indexer's pipeline (app/indexer.py).
    stage 0 = its contents still need reading/embedding, stage 1 = fully searchable.
    priority orders the work: lower runs first (documents before code before images,
    most recently modified first within each)."""

    __tablename__ = "index_state"
    __table_args__ = (Index("ix_index_state_stage_priority", "stage", "priority"),)

    file_id: int = Field(primary_key=True, foreign_key="files.id")
    stage: int = Field(default=0)
    priority: int = Field(default=0)
