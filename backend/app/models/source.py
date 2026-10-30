from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, Timestamps, UUIDPrimaryKey


class NewsSource(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "news_sources"
    __table_args__ = (
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        CheckConstraint("btrim(url) <> ''", name="url_not_blank"),
        CheckConstraint("btrim(connector) <> ''", name="connector_not_blank"),
    )

    name: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, unique=True)
    connector: Mapped[str] = mapped_column(String(32), default="wordpress", server_default="wordpress")
    language: Mapped[str | None] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    articles: Mapped[list["CollectedArticle"]] = relationship(back_populates="source", passive_deletes="all")
