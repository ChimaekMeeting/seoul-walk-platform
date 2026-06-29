"""
기존 UserPreference 가중치를 '새 baseline' 의미로 변환하는 일회성 마이그레이션 스크립트.

배경:
    예전에는 모든 가중치가 0.5에서 시작했으나, 이제 미관·활동·동반 특성
    (nature / running / landmark / child)의 baseline이 0.0(중립)으로 바뀜.
    (route_schema.Weights 기본값 = SSOT)
    → 기존 사용자의 저장값에서 옛 baseline(0.5)을 빼 새 의미로 맞춤.
    → safety / slope는 baseline이 그대로 0.5이므로 변경하지 않음.

변환식:
    new = clamp(old - 0.5, 0.0, 1.0)   (대상: nature, running, landmark, child)

    예) 자연 태그 미선택  0.5 → 0.0  (무편향)
        "나무 많은"(+0.2) 0.7 → 0.2
        두 개 선택(+0.4)  0.9 → 0.4

실행:
    미리보기(기본): poetry run python scripts/migrate_weights_baseline.py
    실제 적용     : poetry run python scripts/migrate_weights_baseline.py --apply

주의:
    반드시 '한 번만' 적용하세요. 두 번 적용하면 0.5를 두 번 빼서 값이 망가집니다.
    (멱등하지 않음 — 적용 후 재실행 금지)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(encoding="utf-8")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# 매퍼 등록용 — User의 relationship이 참조하는 엔티티들을 모두 import해야
# SQLAlchemy가 관계명을 해석할 수 있음 (미import 시 'ChatSession' 등 resolve 실패)
from src.entity.user import User            # noqa: F401
from src.entity.chat_session import ChatSession  # noqa: F401
from src.entity.route_history import RouteHistory  # noqa: F401
from src.entity.banner import Banner        # noqa: F401
from src.entity.user_preference import UserPreference

# 옛 baseline(모든 특성 0.5 시작) — 새 baseline이 0.0인 특성에서만 빼냄
_OLD_BASELINE = 0.5
_TARGET_FIELDS = ("weights_nature", "weights_running", "weights_landmark", "weights_child")

DB_URL = (
    f"postgresql+psycopg2://"
    f"{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}"
    f"/{os.getenv('POSTGRES_DB')}?client_encoding=utf8"
)

engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)


def _convert(value):
    """옛 baseline(0.5)을 뺀 새 값으로 변환함. None은 건드리지 않음."""
    if value is None:
        return None
    return round(max(0.0, min(1.0, value - _OLD_BASELINE)), 4)


def main(apply: bool) -> None:
    with Session() as db:
        rows = db.execute(select(UserPreference)).scalars().all()

        changed = 0
        for pref in rows:
            diffs = []
            for field in _TARGET_FIELDS:
                old = getattr(pref, field)
                new = _convert(old)
                if new is not None and new != old:
                    diffs.append(f"{field}: {old} → {new}")
                    if apply:
                        setattr(pref, field, new)
            if diffs:
                changed += 1
                print(f"[user_id={pref.user_id}] " + ", ".join(diffs))

        if apply:
            db.commit()
            print(f"\n✅ 적용 완료: {changed}개 레코드 변경")
        else:
            print(f"\n[DRY-RUN] 변경 예정 레코드: {changed}개")
            print("실제로 반영하려면 --apply 를 붙여 다시 실행하세요. (한 번만!)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UserPreference 가중치 baseline 마이그레이션")
    parser.add_argument("--apply", action="store_true", help="실제로 DB에 반영 (미지정 시 dry-run)")
    main(parser.parse_args().apply)
