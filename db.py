from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DB_URL = "sqlite+aiosqlite:///vector.db"

engine = create_async_engine(DB_URL)
async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), unique=True, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(512), unique=True)
    source_type: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def create_post(title: str, content: str, source_url: str | None = None) -> Post:
    async with async_session() as session:
        post = Post(title=title, content=content, source_url=source_url)
        session.add(post)
        await session.commit()
        await session.refresh(post)
        return post


async def get_post(post_id: int) -> Post | None:
    async with async_session() as session:
        return await session.get(Post, post_id)


async def set_post_status(post_id: int, status: str) -> None:
    async with async_session() as session:
        post = await session.get(Post, post_id)
        if post is not None:
            post.status = status
            await session.commit()


async def update_post_content(post_id: int, content: str) -> None:
    async with async_session() as session:
        post = await session.get(Post, post_id)
        if post is not None:
            post.content = content
            await session.commit()


async def url_exists(url: str) -> bool:
    async with async_session() as session:
        result = await session.execute(select(Post).where(Post.source_url == url))
        return result.scalar_one_or_none() is not None