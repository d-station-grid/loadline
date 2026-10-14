from fastapi import APIRouter

from app.models import User
from app.routers.deps import CurrentUser, DbSession
from app.schemas.settings import IngestTokenOut, SettingsFields, SettingsIn, SettingsOut
from app.services.ingest_tokens import current_token, issue_token

router = APIRouter(prefix="/settings", tags=["settings"])


async def _settings_out(session: DbSession, user: User) -> SettingsOut:
    token = await current_token(session, user.id)
    fields = SettingsFields.model_validate(user)
    return SettingsOut(
        **fields.model_dump(), ingest_token_last_four=token.last_four if token else None
    )


@router.get("", response_model=SettingsOut)
async def read_settings(user: CurrentUser, session: DbSession) -> SettingsOut:
    return await _settings_out(session, user)


@router.put("", response_model=SettingsOut)
async def update_settings(body: SettingsIn, user: CurrentUser, session: DbSession) -> SettingsOut:
    """設定をまとめて書き換える。検証は SettingsIn が済ませている。"""
    for name, value in body.model_dump().items():
        setattr(user, name, value)
    await session.commit()
    return await _settings_out(session, user)


@router.post("/ingest-token", response_model=IngestTokenOut)
async def reissue_ingest_token(user: CurrentUser, session: DbSession) -> IngestTokenOut:
    """取り込み用トークンを発行する。すでにあれば無効にして新しくする。平文はこの返事だけ。"""
    token, row = await issue_token(session, user.id)
    return IngestTokenOut(token=token, last_four=row.last_four)
