from fastapi import APIRouter

from app.routers.deps import GUEST_FORBIDDEN, CurrentUser, DbSession, WritableUser
from app.schemas.settings import IngestTokenOut, SettingsIn, SettingsOut
from app.services import settings as settings_service
from app.services.ingest_tokens import issue_token

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
async def read_settings(user: CurrentUser, session: DbSession) -> SettingsOut:
    return await settings_service.read_settings(session, user)


@router.put("", response_model=SettingsOut, responses=GUEST_FORBIDDEN)
async def update_settings(body: SettingsIn, user: WritableUser, session: DbSession) -> SettingsOut:
    """設定をまとめて書き換える。検証は SettingsIn が済ませている。"""
    return await settings_service.update_settings(session, user, body)


@router.post("/ingest-token", response_model=IngestTokenOut, responses=GUEST_FORBIDDEN)
async def reissue_ingest_token(user: WritableUser, session: DbSession) -> IngestTokenOut:
    """取り込み用トークンを発行する。すでにあれば無効にして新しくする。平文はこの返事だけ。"""
    token, row = await issue_token(session, user.id)
    return IngestTokenOut(token=token, last_four=row.last_four)
