from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.schemas.settings import SettingsFields, SettingsIn, SettingsOut
from app.services.ingest_tokens import current_token


async def read_settings(session: AsyncSession, user: User) -> SettingsOut:
    """設定の列と、いま有効な取り込み用トークンの末尾 4 文字。"""
    token = await current_token(session, user.id)
    fields = SettingsFields.model_validate(user)
    return SettingsOut(
        **fields.model_dump(), ingest_token_last_four=token.last_four if token else None
    )


async def update_settings(session: AsyncSession, user: User, body: SettingsIn) -> SettingsOut:
    """設定をまとめて書き換える。検証は SettingsIn が済ませている。"""
    for name, value in body.model_dump().items():
        setattr(user, name, value)
    await session.commit()
    return await read_settings(session, user)
