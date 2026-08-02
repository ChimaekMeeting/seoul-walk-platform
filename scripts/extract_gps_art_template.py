"""
이미지 실루엣 → GPS Art 템플릿 좌표 추출기

이미지에서 배경을 제거해 실루엣(이진 마스크)을 얻고, 윤곽선을 둘레 기준으로 균등한
간격으로 샘플링해 (0, 0) 시작·종료인 닫힌 좌표열을 출력합니다.
출력을 그대로 `src/agent/tools/gps_art_templates.py`의 GPS_ART_TEMPLATES에 붙여넣으면 됩니다.

이 스크립트는 오프라인 저작 도구이며, 런타임 서비스에는 포함되지 않습니다.
opencv-python·numpy·openai·python-dotenv는 pyproject.toml/requirements.txt에 선언된
프로젝트 의존성이므로 별도 설치가 필요 없습니다.

이미지는 항상 pictures/{이름}.png를 사용합니다(전체 경로가 아니라 도형 이름만 입력).
pictures/{이름}.png가 이미 있으면 AI를 호출하지 않고 그 파일을 그대로 사용합니다(비용 절감).
없으면 OpenAI gpt-image-1-mini로 자동 생성해 그 경로에 저장하며, 흰 배경·굵은 검은 외곽선·
그림자 없음·바닥선 없음 스타일이 모든 도형에 항상 고정 적용됩니다.
(.env에 OPENAI_API_KEY 필요 — 이 프로젝트가 이미 사용 중인 것과 동일)

SCALE·INTERVAL은 모든 템플릿에 동일하게 적용되는 고정값입니다(아래 상수 참고).

사용법:
  python scripts/extract_gps_art_template.py 강아지   # pictures/강아지.png 사용 또는 생성
"""
import argparse
import base64
import os
import sys

import cv2
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔 기본 코드페이지에서 한글 깨짐 방지
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")  # parser.error() 등 stderr 출력도 동일하게 처리

# gps_art_proposal.md D7과 동일한 상수(F7 walk_nodes 최근접 거리 실측 기반).
TARGET_NODE_SPACING_M = 20.0
NETWORK_FACTOR = 1.4

SCALE = 30  # 출력 좌표의 최대 변 길이. 모든 템플릿이 같은 좌표계를 쓰도록 고정.
INTERVAL = 0.3  # 출력 좌표계(SCALE 기준) 점 간격. 작을수록 곡선을 촘촘히 따라가 점 개수가 늘어남.


def generate_image(shape: str, save_path: str) -> None:
    """
    OpenAI gpt-image-1-mini로 shape(도형 이름)의 실루엣 이미지를 생성해 save_path에 저장합니다.
    shape 외 나머지 스타일(흰 배경·굵은 검은 외곽선·그림자·바닥선 없음)은 고정 템플릿으로,
    모든 도형에 항상 같은 스타일을 적용해 배경 제거·윤곽선 추출 품질을 일정하게 유지합니다.
    """
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        sys.exit("환경변수 OPENAI_API_KEY가 없습니다(.env 확인).")

    styled_prompt = (
        f"A {shape} solid silhouette icon, single flat black shape filled solid. "
        f"Solid white background. No internal lines, no internal details, no highlights, no texture inside the shape. "
        f"No shadow. No ground line. No text. No gradient. Centered, simple flat icon."
    )
    print(f"이미지 생성 중... prompt: {styled_prompt}")

    client = OpenAI(api_key=api_key)
    result = client.images.generate(model="gpt-image-1-mini", prompt=styled_prompt, size="1024x1024", n=1)
    image_bytes = base64.b64decode(result.data[0].b64_json)
    with open(save_path, "wb") as f:
        f.write(image_bytes)
    print(f"이미지 저장됨: {save_path}")


def _finalize_mask(mask: "np.ndarray") -> "np.ndarray":
    """
    실루엣 내부의 얇은 틈(장식선 등)을 morphological closing으로 메워
    윤곽선 추적이 그 틈으로 파고들었다 되돌아나오는 지그재그를 방지합니다.
    """
    # 이미지 해상도에 비례한 커널(짧은 변의 약 2%)이어야 장식선 두께의 틈도 안정적으로 메움
    k = max(3, round(min(mask.shape[:2]) * 0.02)) | 1  # 홀수로 보정
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)


def load_mask(image_path: str) -> "np.ndarray":
    """
    이미지를 읽어 전경(피사체)=255, 배경=0인 이진 마스크를 반환합니다.
    """
    # cv2.imread는 Windows에서 비-ASCII(한글 등) 경로를 못 읽는 경우가 있어,
    # 파일은 Python 자체 I/O로 읽고 cv2.imdecode로 디코딩한다.
    try:
        file_bytes = np.fromfile(image_path, dtype=np.uint8)
    except OSError:
        sys.exit(f"이미지를 읽을 수 없습니다: {image_path}")
    gray = cv2.imdecode(file_bytes, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        sys.exit(f"이미지를 읽을 수 없습니다: {image_path}")

    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 배경은 보통 이미지 모서리와 같은 값 → 모서리가 흰(255) 쪽이면 반전해 피사체를 255로 맞춤
    border = np.concatenate([mask[0, :], mask[-1, :], mask[:, 0], mask[:, -1]])
    if np.mean(border) > 127:
        mask = cv2.bitwise_not(mask)
    return _finalize_mask(mask)


def get_largest_contour(mask: "np.ndarray") -> "np.ndarray":
    """
    마스크에서 가장 큰 윤곽선을 (N, 2) pixel 좌표 배열로 반환합니다.
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        sys.exit("윤곽선을 찾지 못했습니다. 배경 제거 결과를 확인하세요.")
    return max(contours, key=cv2.contourArea).reshape(-1, 2)


def _perimeter_px(contour: "np.ndarray") -> float:
    """윤곽선(닫힌 다각형, pixel 좌표)의 전체 둘레 길이(pixel)를 반환합니다."""
    diffs = np.diff(contour, axis=0, append=contour[:1])
    return float(np.sqrt((diffs ** 2).sum(axis=1)).sum())


def resolve_point_count(contour: "np.ndarray", scale: float, interval: float) -> int:
    """
    출력 좌표계(scale 기준) 점 간격에 맞는 점 개수를 둘레 길이로부터 역산합니다.
    간격이 좁을수록(곡선을 촘촘히 따라갈수록) 점 개수가 자동으로 늘어납니다.
    """
    xs, ys = contour[:, 0], contour[:, 1]
    width = xs.max() - xs.min() or 1
    height = ys.max() - ys.min() or 1
    factor = scale / max(width, height)  # pixel → 출력 좌표계 배율(normalize_points와 동일 기준)

    perimeter_out = _perimeter_px(contour) * factor  # 출력 좌표계 기준 전체 둘레
    return max(round(perimeter_out / interval), 8)


def extract_contour_points(contour: "np.ndarray", n_points: int) -> list[tuple[int, int]]:
    """
    윤곽선을 둘레 기준으로 n_points개 균등 샘플링합니다.
    """
    diffs = np.diff(contour, axis=0, append=contour[:1])
    seg_len = np.sqrt((diffs ** 2).sum(axis=1))
    cum_len = np.concatenate([[0], np.cumsum(seg_len)])
    total_len = cum_len[-1]

    targets = np.linspace(0, total_len, n_points, endpoint=False)
    sampled = []
    for t in targets:
        idx = min(int(np.searchsorted(cum_len, t, side="right") - 1), len(contour) - 1)
        sampled.append(tuple(int(v) for v in contour[idx]))
    return sampled


def _drop_collinear(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """
    연속된 점 3개 이상이 같은 x 또는 같은 y(축 정렬 직선)를 이루면 방향이 바뀌지 않는
    구간이므로 중간 점을 버리고 양 끝점만 남깁니다.
    """
    result = points[:2]
    for p in points[2:]:
        a, b = result[-2], result[-1]
        if (a[0] == b[0] == p[0]) or (a[1] == b[1] == p[1]):
            result[-1] = p  # 직선 연장: 중간점을 새 끝점으로 대체
        else:
            result.append(p)
    return result


def normalize_points(points: list[tuple[int, int]], scale: float) -> list[tuple[int, int]]:
    """
    (0, 0) 시작 상대 좌표로 변환합니다: bounding box를 scale 크기로 맞추고,
    이미지 좌표계(y 아래로 증가)를 지도 관례(y 위로 증가)에 맞게 뒤집은 뒤 정수로 반올림하고,
    같은 x 또는 y로 이어지는 직선 구간은 양 끝점만 남깁니다.
    첫 점을 다시 추가해 시작=끝인 닫힌 도형으로 만듭니다.
    """
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    width = max(xs) - min(xs) or 1
    height = max(ys) - min(ys) or 1
    factor = scale / max(width, height)

    x0, y0 = points[0]
    result = []
    for x, y in points:
        nx = round((x - x0) * factor)
        ny = round(-(y - y0) * factor)  # y축 반전(이미지 아래→지도 위)
        if result and result[-1] == (nx, ny):
            continue  # 정수 반올림으로 직전 점과 좌표가 겹치면 건너뜀(0-length 구간 방지)
        result.append((nx, ny))
    result = _drop_collinear(result)
    result.append(result[0])  # 시작점 = 끝점 (닫힌 도형)
    return result


def main():
    parser = argparse.ArgumentParser(description="이미지 실루엣에서 GPS Art 템플릿 좌표를 추출합니다.")
    parser.add_argument("image", help="도형 이름. pictures/{이름}.png를 사용합니다(전체 경로가 아닌 이름만 입력). 없으면 gpt-image-1-mini로 생성해 그 경로에 저장")
    args = parser.parse_args()

    os.makedirs("pictures", exist_ok=True)
    image_path = os.path.join("pictures", f"{args.image}.png")

    if os.path.exists(image_path):
        print(f"기존 이미지 사용(AI 호출 생략): {image_path}")
    else:
        generate_image(args.image, image_path)

    mask = load_mask(image_path)
    contour = get_largest_contour(mask)
    n_points = resolve_point_count(contour, SCALE, INTERVAL)
    raw_points = extract_contour_points(contour, n_points)
    points = normalize_points(raw_points, SCALE)

    print(f"# {image_path} -> {len(points)}개 점 (닫힌 도형)")
    literal = ", ".join(f"Point(x={x}, y={y})" for x, y in points)
    print(f"[{literal}]")

    # D7 다운샘플링 공식(gps_art_proposal.md)의 역산: target_km이 이보다 작으면
    # 런타임에서 n_used < len(points)로 클램프되어 코너 일부가 잘려 모양이 무너진다.
    min_km = len(points) * TARGET_NODE_SPACING_M * NETWORK_FACTOR / 1000
    print(f"\n이 {len(points)}개 점이 전부 살아남으려면 target_km >= {min_km:.2f}km 이상으로 요청해야 합니다"
          f"(점당 간격 {TARGET_NODE_SPACING_M}m, 도로망 계수 {NETWORK_FACTOR} 기준).")


if __name__ == "__main__":
    main()
