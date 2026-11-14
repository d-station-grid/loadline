"""週次レビューを作る材料。"""

from dataclasses import dataclass

from app.domain.effort import NO_EFFORT, Effort
from app.domain.fallback_review import ReviewOption
from app.domain.situation import WeekSituation


@dataclass(frozen=True)
class ReviewMaterial:
    """その週の判定と、ちょうど 1 週前の週次レビューで本人が選んだ選択肢（選んでいなければ None）。

    effort は練習の量と強度の配分の判定。量が多めの週は、量を増やす選択肢を出さない。

    定型のセリフは week だけを使い、前の週の選択は読まない。LLM でセリフを作るときに、
    選んだ過ごし方と今週の数字を合わせて話せるように渡す。
    """

    week: WeekSituation
    previous_choice: ReviewOption | None
    effort: Effort = NO_EFFORT
