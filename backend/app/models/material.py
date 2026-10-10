"""Versioned project evidence. Project management fields are never prompt sources."""
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from .taxonomy import utc_now


class Project(Base):
    __tablename__ = 'project'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(240))
    summary: Mapped[str] = mapped_column(Text, default='', server_default='')
    tech_stack: Mapped[str] = mapped_column(Text, default='', server_default='')
    personal_role: Mapped[str] = mapped_column(Text, default='', server_default='')
    challenges: Mapped[str] = mapped_column(Text, default='', server_default='')
    outcomes: Mapped[str] = mapped_column(Text, default='', server_default='')
    highlights: Mapped[str] = mapped_column(Text, default='', server_default='')
    notes: Mapped[str] = mapped_column(Text, default='', server_default='')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text('1'))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, server_default=func.current_timestamp())


class Material(Base):
    __tablename__ = 'material'
    __table_args__ = (
        CheckConstraint("kind IN ('resume','project_profile','project_brief','readme','architecture_doc','other')", name='ck_material_kind'),
        CheckConstraint("(kind = 'project_profile' AND is_system_managed = 1 AND project_id IS NOT NULL) OR (kind != 'project_profile' AND is_system_managed = 0)", name='ck_material_profile_owner'),
        Index('uq_material_project_profile', 'project_id', unique=True, sqlite_where=text("kind = 'project_profile' AND is_system_managed = 1")),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    project_id: Mapped[int | None] = mapped_column(ForeignKey('project.id', ondelete='RESTRICT'), index=True)
    title: Mapped[str] = mapped_column(String(240))
    original_filename: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text('1'))
    include_in_context: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text('1'))
    is_system_managed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text('0'))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, server_default=func.current_timestamp())


class MaterialVersion(Base):
    __tablename__ = 'material_version'
    __table_args__ = (UniqueConstraint('material_id','version_no',name='uq_material_version_no'),
        CheckConstraint('version_no > 0',name='ck_material_version_no'))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey('material.id', ondelete='RESTRICT'), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    parsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, server_default=func.current_timestamp())


class MaterialChunk(Base):
    __tablename__ = 'material_chunk'
    __table_args__ = (UniqueConstraint('material_version_id','ordinal',name='uq_material_chunk_ordinal'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_version_id: Mapped[int] = mapped_column(ForeignKey('material_version.id', ondelete='RESTRICT'), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey('project.id', ondelete='RESTRICT'))
    ordinal: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(String(240))
    text: Mapped[str] = mapped_column(Text)
