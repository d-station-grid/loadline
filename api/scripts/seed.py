"""Health Auto Export の JSON を手元の DB に取り込む。

使い方（api/ で）:
  uv run python -m scripts.seed --email you@example.com ../notes/sample_*.json
  uv run python -m scripts.seed --demo ../notes/*.json ../../loadline-spike/receiver/received/*.json

--email はログインずみの利用者（users.email）に入れる。--demo はデモ用の利用者（is_demo、
firebase_uid は NULL）を作って入れる。あとでゲストに見せるデータの種になる。
受け口と同じ ingest() を通るので、Apple Watch 以外は入らず、同じ記録は二重にならない。
"""

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.db import get_session_factory
from app.models import User
from app.schemas.ingest import IngestPayload
from app.services.ingest import ingest

DEMO_EMAIL = "demo@loadline.invalid"


async def main(email: str | None, demo: bool, files: list[Path]) -> None:
    async with get_session_factory()() as session:
        if demo:
            user = await session.scalar(select(User).where(User.is_demo.is_(True)))
            if user is None:
                user = User(email=DEMO_EMAIL, is_demo=True)
                session.add(user)
                await session.flush()
        else:
            user = await session.scalar(select(User).where(User.email == email))
            if user is None:
                raise SystemExit(f"no user with email {email}. Log in once first.")

        for path in files:
            payload = IngestPayload.model_validate(json.loads(path.read_text()))
            result = await ingest(session, user.id, payload)
            print(f"{path.name}: {result.model_dump()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--email", help="ログインずみの利用者のメール")
    who.add_argument("--demo", action="store_true", help="デモ用の利用者に入れる")
    parser.add_argument("files", nargs="+", type=Path, help="Health Auto Export の JSON")
    args = parser.parse_args()
    asyncio.run(main(args.email, args.demo, args.files))
