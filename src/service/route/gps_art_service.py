import base64
import logging
import os
from typing import List, Optional

import cv2
import numpy as np

from src.infrastructure.external.client.gpt_client import GPTClient
from src.interfaces.schema.auth_schema import Status
from src.schema.route_schema import GpsArtPoint
from src.service.user.auth_service import AuthService

logger = logging.getLogger(__name__)

_PICTURES_DIR = "pictures"
_IMAGE_MODEL = "gpt-image-1-mini"  # 단순 실루엣 아이콘이라 저렴한 모델로 충분
# cv2.approxPolyDP 허용 오차(픽셀 고정값, 둘레 비율이 아님).
# 둘레 비율(예: 0.15%)로 잡으면 이미지를 확대해도 상대 오차가 그대로라 점 개수가
# 거의 안 늘어난다(스케일 불변) — 이미지를 키웠을 때 실제로 더 촘촘해지게 하려면
# 이렇게 절대 픽셀값으로 고정해야 한다. 1024px 우산 이미지(perimeter≈3236px) 기준
# 실측: 1px->119점, 2px->83점, 3px->69점, 5px->51점, 8px->39점.
# leg가 늘어날수록 도로망 격자 노이즈에 취약해지고 leg 하나 실패 시
# WaypointComposerEngine이 그 지점에서 전체 경로를 자르므로, 무작정 낮추지 말 것.
_APPROX_EPSILON_PX = 2.0


class GpsArtService:
    def __init__(self, auth_service: AuthService, gpt_client: Optional[GPTClient] = None):
        self.auth_service = auth_service
        self.gpt_client = gpt_client or GPTClient()

    async def get_shape_points(
        self,
        access_token: str,
        shape_name: str,
    ) -> Optional[List[GpsArtPoint]]:
        """
        shape_name의 실루엣 이미지(없으면 생성)에서 윤곽선을 추출해 원본 정규화 좌표
        ([(0, 0), ...], 위경도 아님)를 반환합니다. 위경도 매핑은 gps_art.py의
        GpsArtEngine._map_to_geo가 담당하며 여기서는 하지 않습니다.
        인증 실패·윤곽선 추출 실패면 None을 반환합니다.
        """
        auth_status, provider, provider_id = self.auth_service.check_access_token(access_token)
        if auth_status != Status.SUCCESS:
            logger.warning("gps art shape lookup auth failed: shape=%s status=%s", shape_name, auth_status.value)
            return None

        os.makedirs(_PICTURES_DIR, exist_ok=True)
        image_path = os.path.join(_PICTURES_DIR, f"{shape_name}.png")

        if os.path.exists(image_path):
            logger.info("gps art image cache hit: shape=%s path=%s", shape_name, image_path)
        else:
            try:
                await self._generate_image(shape_name, image_path)
            except Exception:
                logger.exception("gps art image generation failed: shape=%s", shape_name)
                return None

        try:
            mask = self._load_mask(image_path)
            contour = self._get_largest_contour(mask)
        except ValueError as e:
            logger.warning("gps art contour extraction failed: shape=%s error=%s", shape_name, e)
            return None

        points = self._extract_shape_points(contour)
        logger.info(
            "gps art shape points extracted: shape=%s count=%d points=%s",
            shape_name, len(points), [(p.x, p.y) for p in points],
        )
        return points

    async def _generate_image(self, shape_name: str, save_path: str) -> None:
        """
        OpenAI Images API로 shape_name의 실루엣 이미지를 생성해 save_path에 저장합니다.
        스타일(흰 배경·굵은 검은 외곽선·그림자·바닥선 없음)은 프롬프트에 고정돼 있어
        어떤 도형이든 배경 제거·윤곽선 추출 품질이 일정하게 유지된다.
        """
        b64_data = await self.gpt_client.generate_image(
            prompt_name="gps_art_image",
            input_variables={"shape": shape_name},
            model=_IMAGE_MODEL,
        )
        image_bytes = base64.b64decode(b64_data)
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        logger.info("gps art image generated: shape=%s path=%s", shape_name, save_path)

    @staticmethod
    def _load_mask(image_path: str) -> np.ndarray:
        """
        이미지를 읽어 전경(피사체)=255, 배경=0인 이진 마스크를 반환합니다.
        """
        # cv2.imread는 Windows에서 비-ASCII(한글 등) 경로를 못 읽는 경우가 있어,
        # 파일은 numpy로 읽고 cv2.imdecode로 디코딩한다.
        file_bytes = np.fromfile(image_path, dtype=np.uint8)
        gray = cv2.imdecode(file_bytes, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise ValueError(f"이미지를 읽을 수 없습니다: {image_path}")

        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # 배경은 보통 이미지 모서리와 같은 값 -> 모서리가 흰(255) 쪽이면 반전해 피사체를 255로 맞춤
        border = np.concatenate([mask[0, :], mask[-1, :], mask[:, 0], mask[:, -1]])
        if np.mean(border) > 127:
            mask = cv2.bitwise_not(mask)

        return GpsArtService._finalize_mask(mask)

    @staticmethod
    def _finalize_mask(mask: np.ndarray) -> np.ndarray:
        """
        실루엣 내부의 얇은 틈(장식선 등)을 morphological closing으로 메워
        윤곽선 추적이 그 틈으로 파고들었다 되돌아나오는 지그재그를 방지합니다.
        """
        k = max(3, round(min(mask.shape[:2]) * 0.02)) | 1  # 홀수로 보정
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    @staticmethod
    def _get_largest_contour(mask: np.ndarray) -> np.ndarray:
        """
        마스크에서 가장 큰 윤곽선을 cv2 원본 형태((N, 1, 2))로 반환합니다.
        """
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            raise ValueError("윤곽선을 찾지 못했습니다. 배경 제거 결과를 확인하세요.")
        return max(contours, key=cv2.contourArea)

    def _extract_shape_points(self, contour: np.ndarray) -> List[GpsArtPoint]:
        """
        윤곽선을 (0, 0) 시작 상대 좌표로 변환합니다. 균등 간격 샘플링 대신
        cv2.approxPolyDP로 도형이 실제로 꺾이는 지점만 남깁니다 — 직선 구간은
        점 간격과 무관하게 양 끝점만 남고, 곡선은 굴곡에 따라 필요한 만큼만 남습니다.
        """
        approx = cv2.approxPolyDP(contour, _APPROX_EPSILON_PX, closed=True)
        raw_points = [tuple(int(v) for v in pt[0]) for pt in approx]
        return self._normalize_points(raw_points)

    @staticmethod
    def _normalize_points(points: list[tuple[int, int]]) -> List[GpsArtPoint]:
        """
        (0, 0) 시작 상대 좌표로 변환합니다. 절대 스케일은 GpsArtEngine._map_to_geo가
        target_km 대비 둘레 비율로 다시 계산하므로 여기서 맞출 필요가 없고, y축만
        이미지 좌표계(아래로 증가)에서 지도 관례(위로 증가)로 뒤집으면 됩니다.
        """
        x0, y0 = points[0]
        return [GpsArtPoint(x=x - x0, y=-(y - y0)) for x, y in points]
