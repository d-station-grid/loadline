"""Firebase Authentication の利用者を消す。

ID トークンの検証（core/auth.py）とは別の app を使う。検証は資格情報が要らないが、
管理の機能は Google に認証が要るので、こちらは Application Default Credentials で
初期化する。資格情報を読むのは初めて消すときなので、CI など資格情報のない環境でも
起動や import では落ちない。本番は Cloud Run のサービスアカウントで、Firebase
Authentication の管理者のロールが要る。
"""

import asyncio
import logging
import threading

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials as firebase_credentials
from firebase_admin.exceptions import FirebaseError
from google.auth.exceptions import GoogleAuthError

from app.core.config import Settings
from app.services.accounts import AccountDeleteError

logger = logging.getLogger(__name__)

# 検証の app（名前は [DEFAULT]）と分ける
APP_NAME = "account-admin"


class FirebaseAccountDeleter:
    def __init__(self, project_id: str) -> None:
        self._project_id = project_id
        self._app: firebase_admin.App | None = None
        self._lock = threading.Lock()

    def _admin(self) -> firebase_admin.App:
        # 初期化は初めて消すときに 1 回だけ。to_thread の別のスレッドから同時に来てもよいようにする
        with self._lock:
            if self._app is None:
                try:
                    self._app = firebase_admin.get_app(APP_NAME)
                except ValueError:
                    self._app = firebase_admin.initialize_app(
                        firebase_credentials.ApplicationDefault(),
                        options={"projectId": self._project_id},
                        name=APP_NAME,
                    )
            return self._app

    def _delete(self, uid: str) -> None:
        try:
            firebase_auth.delete_user(uid, app=self._admin())
        except firebase_auth.UserNotFoundError:
            # もう消えている（前の削除が Firebase だけ済んだ、手で消した）。消えたものとして続ける
            logger.info("firebase: user %s is already gone", uid)
        except (FirebaseError, GoogleAuthError, ValueError) as e:
            raise AccountDeleteError from e

    async def delete(self, uid: str) -> None:
        """uid の利用者を消す。SDK は同期なので、別のスレッドで待つ。

        消せなかったときは AccountDeleteError を上げる。呼ぶ側が DB を巻き戻す。
        """
        await asyncio.to_thread(self._delete, uid)


def account_deleter(settings: Settings) -> FirebaseAccountDeleter:
    """設定から作る。ここではまだ資格情報を読まない。"""
    return FirebaseAccountDeleter(settings.firebase_project_id)
