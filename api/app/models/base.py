from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """すべてのモデルの土台。Base.metadata がテーブルの一覧を持つ。"""
