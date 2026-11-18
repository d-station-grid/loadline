from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.language import Language
from app.models import User
from app.schemas.settings import SettingsFields, SettingsIn, SettingsOut
from app.services.ingest_tokens import current_token


async def read_settings(session: AsyncSession, user: User) -> SettingsOut:
    """設定の列と、いま有効な取り込み用トークンの末尾 4 文字と、最後に取り込めた日時。"""
    token = await current_token(session, user.id)
    fields = SettingsFields.model_validate(user)
    return SettingsOut(
        **fields.model_dump(),
        ingest_token_last_four=token.last_four if token else None,
        last_received_at=user.last_ingested_at,
    )


async def update_settings(session: AsyncSession, user: User, body: SettingsIn) -> SettingsOut:
    """設定をまとめて書き換える。検証は SettingsIn が済ませている。

    言語を省略していたら、保存済みの言語を残す。
    """
    exclude = set() if "language" in body.model_fields_set else {"language"}
    for name, value in body.model_dump(exclude=exclude).items():
        setattr(user, name, value)
    await session.commit()
    return await read_settings(session, user)


async def update_language(session: AsyncSession, user: User, language: Language) -> SettingsOut:
    """言語だけを書き換える。ほかの設定には触らない。"""
    user.language = language
    await session.commit()
    return await read_settings(session, user)
