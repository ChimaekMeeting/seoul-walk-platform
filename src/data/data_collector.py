import argparse
import logging

from src.data import (
    BaseNetworkCollector,
    NatureCollector,
    SafetyCollector,
    LandmarkCollector,
    RunningCourseCollector,
    ChildCollector,
    CommercialCollector,
    EdgeFeatureCollector,
    RoutePoiCollector,
    SeoulBoundaryCollector,
    SeoulWaterCollector,
    ParkPolygonCollector,
)

logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="서비스용 도메인 데이터를 적재합니다.")
    parser.add_argument(
        "--scope",
        choices=("v1", "legacy-all"),
        default="v1",
        help="v1은 승인된 필수 데이터만, legacy-all은 기존 전체 파이프라인을 실행합니다.",
    )
    parser.add_argument(
        "--network-mode",
        choices=("upsert", "rebuild"),
        default="upsert",
        help="upsert는 기존 score를 보존하고, rebuild는 네트워크 전체를 교체합니다.",
    )
    return parser.parse_args()


def collect_network(network_mode: str) -> None:
    network_collector = BaseNetworkCollector()
    if network_mode == "upsert":
        logger.info("--- 도보 네트워크 증분 갱신(upsert) ---")
        network_collector.upsert()
    elif network_mode == "rebuild":
        logger.warning("--- 도보 네트워크 전체 재구축(rebuild) ---")
        network_collector.rebuild()
    else:
        raise ValueError(f"지원하지 않는 네트워크 적재 모드: {network_mode}")


def collect_v1(network_mode: str) -> None:
    """
    V1에서 승인된 필수 데이터만 적재합니다.

    서울 경계와 수계는 score 원본이 아니라 API 좌표 유효성 검증에 필요한
    서비스 인프라입니다.
    """
    collect_network(network_mode)

    logger.info("--- 서울 행정구역 경계 적재 ---")
    SeoulBoundaryCollector().save()

    logger.info("--- 서울시 공원 Polygon 적재·WalkEdge 매핑 ---")
    ParkPolygonCollector().save()

    logger.info("--- CCTV·스마트가로등 안전 Layer·Score 적재 ---")
    SafetyCollector().save()

    logger.info("--- 어린이보호구역 Layer·차량 주의 Edge 적재 ---")
    ChildCollector().save(include_play_facility=False)

    logger.info("--- 외부 선형 Edge 검증 후보 Layer 적재 ---")
    EdgeFeatureCollector().save()

    logger.info("--- 편의·교통·접근성 POI 적재·도보망 연결 ---")
    RoutePoiCollector().save()

    logger.info("--- 상권 편의 Score 적재 ---")
    CommercialCollector().save()

    logger.info("--- 서울 수계 폴리곤 적재 ---")
    SeoulWaterCollector().save()

    logger.info(
        "V1 보류 Collector는 실행하지 않습니다: "
        "OSM nature, landmark, running, slope"
    )


def collect_legacy_all(network_mode: str) -> None:
    """기존 전체 Layer·Score 파이프라인을 명시적으로 실행합니다."""
    collect_network(network_mode)

    logger.info("--- 자연 데이터 적재 ---")
    NatureCollector().save()

    logger.info("--- 안전 데이터 적재 ---")
    SafetyCollector().save()

    logger.info("--- 어린이 시설 적재 ---")
    ChildCollector().save()

    logger.info("--- 서울 행정구역 경계 적재 ---")
    SeoulBoundaryCollector().save()

    logger.info("--- 서울 수계 폴리곤 적재 ---")
    SeoulWaterCollector().save()

    logger.info("--- 랜드마크 적재 ---")
    LandmarkCollector().save()

    logger.info("--- 사고 다발지역 적재 ---")
    SafetyCollector().update_accident()

    logger.info("--- 실외운동기구 적재 ---")
    RunningCourseCollector().update_outdoor_exercise()


def collect(network_mode: str = "upsert", scope: str = "v1") -> None:
    if scope == "v1":
        collect_v1(network_mode)
        return
    if scope == "legacy-all":
        collect_legacy_all(network_mode)
        return
    raise ValueError(f"지원하지 않는 적재 범위: {scope}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(name)s] %(message)s")
    args = parse_args()
    collect(network_mode=args.network_mode, scope=args.scope)
