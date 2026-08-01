"""
테스트용 JWT access token 생성기
.env의 ACCESS_SECRET_KEY를 읽어 72시간 유효한 토큰을 출력합니다.

사용법:
  python scripts/gen_test_token.py
  python scripts/gen_test_token.py --provider-id my_test_id
"""
import argparse
import datetime
import os
import sys

try:
    import jwt
except ImportError:
    sys.exit("PyJWT 미설치: pip install PyJWT")

try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("python-dotenv 미설치: pip install python-dotenv")

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider-id", default="test_9999",
                        help="토큰에 담을 provider_id (기본: test_9999)")
    parser.add_argument("--hours", type=int, default=72,
                        help="토큰 유효 시간(시간 단위, 기본: 72)")
    args = parser.parse_args()

    secret = os.getenv("ACCESS_SECRET_KEY")
    if not secret:
        sys.exit("오류: .env에 ACCESS_SECRET_KEY가 없습니다.")

    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "provider": "kakao",
        "provider_id": args.provider_id,
        "exp": now + datetime.timedelta(hours=args.hours),
        "type": "access",
    }

    token = jwt.encode(payload, secret, algorithm="HS256")
    exp_kst = (payload["exp"] + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M KST")

    print(f"provider_id : {args.provider_id}")
    print(f"expires_at  : {exp_kst}")
    print(f"token       : {token}")

if __name__ == "__main__":
    main()
