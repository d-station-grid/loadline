"""その週の練習の量と強度の配分の判定。DB もタイムゾーンも持ち込まない。

状況の判定（situation）が疲労と記録の有無を見るのに対し、こちらは「どれだけ、どう練習したか」を
見る。数値の比較はここで行い、LLM には結果だけを渡す。

練習の量は、一般の平均とは比べず、本人の過去の週と比べる。負荷は最大心拍と安静時心拍で
目盛りが人ごとに変わり、種目や目標でも量が大きく違うため。比べ方は、その週の負荷 ÷ 過去
9 週の週の負荷の平均（負荷の比）。境目は Garmin の負荷の比（0.8 未満は少なめ、0.8〜1.4 は
適正、1.5〜は多め）にならい、1.4〜1.5 は「いつもどおり」に寄せる。

強度の配分は、強度ごとの時間で見る。中強度が低強度より長ければ「中強度寄り」とするが、
悪いとは決めない。80:20 は週 10 時間以上練習するエリートの配分の記述で、市民ランナーでは
中強度寄りの練習と差が出なかった研究もあるため。高強度の多さは、割合だけでは判定しない。
練習時間の短い人は割合が高めでも量は少ないので、量が「多め」の週に、高強度の時間の増え方が
負荷全体の増え方より大きいときだけ「量が多めで、高強度の時間も増えた」とする。「急に」に
当たるのは負荷全体（普段の 1.5 倍以上）で、高強度について確かめるのは増え方の比べだけ。
過去の高強度が 0 分なら、比べる基準がないので判定しない（量の判定で過去の負荷が 0 のときと
同じ）。0 分から 1 分になっただけで「高強度の時間も増えた」と言わないため。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.domain.load import ZoneTimes

# 比べる過去の週の数（多いとき）
HISTORY_WEEKS = 9
# 比べるのに必要な過去の週の数。これより少なければ、量の判定をしない
MIN_HISTORY_WEEKS = 4
# 負荷の比がこれより下なら「少なめ」
LIGHT_BELOW = 0.8
# 負荷の比がこれ以上なら「多め」
HEAVY_FROM = 1.5


class Volume(StrEnum):
    """その週の負荷を、本人の過去の週の平均と比べた区分。"""

    LIGHT = "light"
    USUAL = "usual"
    HEAVY = "heavy"


@dataclass(frozen=True)
class PastWeek:
    """比べる過去の 1 週。load は負荷の分かる日の負荷の合計、high_sec は高強度の時間。"""

    load: float
    high_sec: int


@dataclass(frozen=True)
class Effort:
    """練習の量と強度の配分の判定。

    volume と load_ratio は、量を判定できなければ None（過去の週が足りない、その週に
    負荷の分からない日がある、過去の負荷が 0）。
    mostly_moderate は、中強度の時間が低強度より長い。強度ごとの時間が分からなければ False。
    hard_went_up は、量が多めで、高強度の時間の増え方が負荷全体の増え方より大きい。
    過去の高強度が 0 分なら判定しない（False）。
    """

    volume: Volume | None
    load_ratio: float | None
    mostly_moderate: bool
    hard_went_up: bool


NO_EFFORT = Effort(volume=None, load_ratio=None, mostly_moderate=False, hard_went_up=False)


def judge_effort(
    load: float,
    unknown_load_days: int,
    zones: ZoneTimes | None,
    history: Sequence[PastWeek],
) -> Effort:
    """その週の練習の量と強度の配分を判定する。

    load はその週の負荷の合計。unknown_load_days はその週の負荷の分からない日の数で、
    1 日でもあれば量は判定しない（負荷が低く出るため）。zones はその週の強度ごとの時間で、
    心拍のないワークアウトがあるか境目が未設定なら None。history は過去の週で古い順。
    記録を始める前の週と、心拍のないワークアウトを含む週は入れない（入れると平均が下がり、
    普段の週も「多め」になる）。
    新しい方から HISTORY_WEEKS 週だけを使い、MIN_HISTORY_WEEKS 週に満たなければ量は
    判定しない。
    """
    recent = list(history)[-HISTORY_WEEKS:]
    ratio = None
    volume = None
    if unknown_load_days == 0 and len(recent) >= MIN_HISTORY_WEEKS:
        usual = sum(w.load for w in recent) / len(recent)
        if usual > 0:
            ratio = load / usual
            if ratio < LIGHT_BELOW:
                volume = Volume.LIGHT
            elif ratio >= HEAVY_FROM:
                volume = Volume.HEAVY
            else:
                volume = Volume.USUAL

    mostly_moderate = zones is not None and zones.mid > zones.low

    hard_went_up = False
    if volume is Volume.HEAVY and ratio is not None and zones is not None:
        usual_high = sum(w.high_sec for w in recent) / len(recent)
        # 過去に高強度がなければ、比べる基準がないので判定しない
        hard_went_up = usual_high > 0 and zones.high / usual_high > ratio

    return Effort(
        volume=volume,
        load_ratio=ratio,
        mostly_moderate=mostly_moderate,
        hard_went_up=hard_went_up,
    )
