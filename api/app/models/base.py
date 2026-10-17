from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """すべてのモデルの土台。Base.metadata がテーブルの一覧を持つ。

    relationship を足すときは lazy="raise" にする。読むときは selectinload などで明示する。
    属性に触れたときに 1 件ずつ読みに行く（N+1）のを、例外で気づけるようにするため。
    tests/test_models.py が検査する。
    """
