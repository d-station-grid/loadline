from app.models import Base


def test_relationships_raise_instead_of_lazy_loading() -> None:
    """relationship は lazy="raise" にする。読み忘れを N+1 ではなく例外で気づけるように。

    読むときは selectinload などで、問い合わせの中で明示的に読む。
    """
    mappers = list(Base.registry.mappers)
    assert mappers

    lazy = [
        f"{m.class_.__name__}.{r.key} (lazy={r.lazy!r})"
        for m in mappers
        for r in m.relationships
        if r.lazy != "raise"
    ]

    assert lazy == []
