from fastapi import APIRouter, status

from app.routers.deps import CurrentUser
from app.schemas.user import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=UserOut,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "ゲスト（匿名ログイン）で入ったが、デモデータがまだ入っていない"
        }
    },
)
async def login(user: CurrentUser) -> UserOut:
    """ID トークンで本人を確かめ、初回なら利用者の行を作って返す。

    アカウントを消した人のトークンは 401（行を作り直さない）。ゲスト（Firebase の匿名
    ログイン）は行を作らず、デモの利用者を返す。
    """
    return UserOut.model_validate(user)
