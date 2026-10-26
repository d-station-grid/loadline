"""振り返りを作る材料。"""

from dataclasses import dataclass

from app.domain.fallback_review import ReviewOption
from app.domain.situation import WeekSituation


@dataclass(frozen=True)
class ReviewMaterial:
    """その週の判定と、ちょうど 1 週前の振り返りで本人が選んだ選択肢（選んでいなければ None）。

    定型のセリフは week だけを使い、前の週の選択は読まない。LLM でセリフを作るときに、
    選んだ過ごし方と今週の数字を合わせて話せるように渡す。
    """

    week: WeekSituation
    previous_choice: ReviewOption | None
