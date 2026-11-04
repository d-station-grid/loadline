from fastapi import APIRouter

from app.routers.deps import CurrentUser
from app.schemas.user import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
async def login(user: CurrentUser) -> UserOut:
    """ID トークンで本人を確かめ、初回なら利用者の行を作って返す。

    アカウントを消した人のトークンは 401（行を作り直さない）。
    """
    return UserOut.model_validate(user)
