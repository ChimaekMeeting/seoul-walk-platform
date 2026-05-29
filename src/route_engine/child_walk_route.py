import math
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree

import networkx as nx
import requests
from dotenv import load_dotenv

from src.interfaces.schema.prewalk_schema import Weights
from src.service.route.route_service import RouteService


load_dotenv()

DEFAULT_PROTECTION_ZONE_XLSX = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "raw"
    / "child_protection_zones_2025_12.xlsx"
)
DEFAULT_PFC3_ENDPOINT = "https://apis.data.go.kr/1741000/pfc3/getPfctInfo3"


@dataclass(frozen=True)
class ChildPlace:
    name: str
    category: str
    source: str
    lat: float | None = None
    lon: float | None = None
    address: str | None = None
    district: str | None = None
    raw: dict[str, Any] | None = None

    @property
    def has_coordinate(self) -> bool:
        return self.lat is not None and self.lon is not None


def get_child_friendly_route(
    context: dict,
    weights: Weights | None = None,
    G_full: nx.Graph | None = None,
    *,
    protection_zone_xlsx: str | Path = DEFAULT_PROTECTION_ZONE_XLSX,
    pfc3_api_key: str | None = None,
    kakao_api_key: str | None = None,
    candidate_count: int = 5,
    corridor_radius_m: float = 250.0,
) -> dict:
    """
    어린이보호구역 + 어린이놀이시설 데이터를 이용해 아이 동반 산책 경로를 고릅니다.

    - 보호구역 엑셀은 도로명 주소만 있으므로 Kakao 키가 있으면 출발 자치구만 좌표로 변환합니다.
    - 놀이시설 API는 data.go.kr 인증키를 인자 또는 환경변수에서 읽습니다.
    - 순환/랜덤 경로는 여러 후보를 만든 뒤 child_index가 가장 높은 경로를 반환합니다.
    """
    child_weights = Weights(
        safety=weights.safety if weights is not None else 1.0,
        nature=weights.nature if weights is not None else 1.0,
    )

    origin = context["origin"]["coordinate"]
    start_lat = float(origin["lat"])
    start_lon = float(origin["lon"])
    distance_km = float(context.get("distance_km", 3.0))
    search_radius_m = max(distance_km * 1000 * 1.5, 1500.0)

    places = load_child_places_near(
        start_lat=start_lat,
        start_lon=start_lon,
        radius_m=search_radius_m,
        protection_zone_xlsx=protection_zone_xlsx,
        pfc3_api_key=pfc3_api_key,
        kakao_api_key=kakao_api_key,
    )

    attempts = max(1, candidate_count if context.get("mode", "circular") == "circular" else 1)
    best_route: dict | None = None
    route_service = RouteService()

    for _ in range(attempts):
        route = route_service.get_route(context, child_weights, G_full)
        if route.get("error"):
            return route

        route = annotate_child_friendliness(
            route,
            places,
            corridor_radius_m=corridor_radius_m,
        )
        if best_route is None or route.get("child_index", 0) > best_route.get("child_index", 0):
            best_route = route

    return best_route or {
        "mode": context.get("mode", "circular"),
        "coordinates": [],
        "total_distance_km": 0.0,
        "error": "아이 동반 산책 경로를 계산하지 못했습니다",
    }


def load_child_places_near(
    *,
    start_lat: float,
    start_lon: float,
    radius_m: float,
    protection_zone_xlsx: str | Path = DEFAULT_PROTECTION_ZONE_XLSX,
    pfc3_api_key: str | None = None,
    kakao_api_key: str | None = None,
) -> list[ChildPlace]:
    """출발지 주변 어린이보호구역과 어린이놀이시설을 합쳐 반환합니다."""
    kakao_key = kakao_api_key or os.getenv("KAKAO_API_KEY")
    pfc_key = (
        pfc3_api_key
        or os.getenv("PFC3_SERVICE_KEY")
        or os.getenv("CHILD_PLAY_API_KEY")
        or os.getenv("DATA_GO_KR_SERVICE_KEY")
    )

    protection_zones = load_child_protection_zones(
        protection_zone_xlsx,
        kakao_api_key=kakao_key,
        center=(start_lat, start_lon),
        radius_m=radius_m,
    )
    play_facilities = fetch_child_play_facilities(
        api_key=pfc_key,
        center=(start_lat, start_lon),
        radius_m=radius_m,
    )

    return protection_zones + play_facilities


def load_child_protection_zones(
    xlsx_path: str | Path = DEFAULT_PROTECTION_ZONE_XLSX,
    *,
    kakao_api_key: str | None = None,
    center: tuple[float, float] | None = None,
    radius_m: float | None = None,
) -> list[ChildPlace]:
    """서울시 어린이보호구역 엑셀에서 시설명/주소를 읽고, 가능하면 좌표를 붙입니다."""
    path = Path(xlsx_path)
    if not path.exists():
        return []

    places: list[ChildPlace] = []
    district_hint = (
        reverse_geocode_district_with_kakao(center[0], center[1], kakao_api_key)
        if center and kakao_api_key
        else None
    )

    for row in _read_child_protection_zone_rows(path):
        district = str(row["district"]).strip()
        if district_hint and district != district_hint:
            continue

        address = _normalize_address(district, row["road_address"])
        lat: float | None = None
        lon: float | None = None

        if kakao_api_key:
            lat, lon = geocode_address_with_kakao(address, kakao_api_key)

        place = ChildPlace(
            name=str(row["name"]).strip(),
            category=str(row.get("facility_type") or "어린이보호구역").strip(),
            source="child_protection_zone_xlsx",
            lat=lat,
            lon=lon,
            address=address,
            district=district,
            raw=row,
        )
        if _is_place_near(place, center, radius_m):
            places.append(place)

    return places


def fetch_child_play_facilities(
    *,
    api_key: str | None = None,
    center: tuple[float, float] | None = None,
    radius_m: float | None = None,
    endpoint: str = DEFAULT_PFC3_ENDPOINT,
    rows: int = 300,
) -> list[ChildPlace]:
    """행정안전부 전국어린이놀이시설정보서비스에서 어린이놀이시설을 조회합니다."""
    if not api_key:
        return []

    params = {
        "serviceKey": api_key,
        "pageNo": 1,
        "numOfRows": rows,
        "type": "json",
    }
    url = f"{endpoint}?{urlencode(params)}"

    try:
        response = requests.get(url, timeout=8)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    places: list[ChildPlace] = []
    for item in _extract_items(payload):
        place = _child_place_from_api_item(item)
        if (
            place
            and _is_operating_play_facility(item)
            and _is_seoul_place(place)
            and _is_place_near(place, center, radius_m)
        ):
            places.append(place)

    return places


def annotate_child_friendliness(
    route: dict,
    child_places: list[ChildPlace],
    *,
    corridor_radius_m: float = 250.0,
) -> dict:
    """경로 주변 어린이 시설 접근성을 계산해 route 딕셔너리에 child_index를 추가합니다."""
    coordinates = route.get("coordinates") or []
    coordinated_places = [p for p in child_places if p.has_coordinate]

    nearby = []
    for place in coordinated_places:
        distance_m = min_distance_to_route_m(coordinates, place.lat, place.lon)
        if distance_m <= corridor_radius_m:
            nearby.append(
                {
                    "name": place.name,
                    "category": place.category,
                    "source": place.source,
                    "address": place.address,
                    "distance_m": round(distance_m, 1),
                    "lat": place.lat,
                    "lon": place.lon,
                }
            )

    protection_count = sum(1 for p in nearby if p["source"] == "child_protection_zone_xlsx")
    play_count = sum(1 for p in nearby if p["source"] == "child_play_facility_api")
    child_index = min(10.0, 3.0 + protection_count * 1.2 + play_count * 1.5)

    route["child_index"] = round(child_index, 1)
    route["child_profile"] = {
        "nearby_child_places": sorted(nearby, key=lambda x: x["distance_m"])[:10],
        "nearby_protection_zone_count": protection_count,
        "nearby_play_facility_count": play_count,
        "loaded_child_place_count": len(child_places),
        "coordinated_child_place_count": len(coordinated_places),
        "corridor_radius_m": corridor_radius_m,
    }
    return route


def min_distance_to_route_m(
    coordinates: list[list[float]],
    lat: float | None,
    lon: float | None,
) -> float:
    if lat is None or lon is None or not coordinates:
        return float("inf")

    return min(_haversine_m(lat, lon, float(p[0]), float(p[1])) for p in coordinates)


def geocode_address_with_kakao(address: str, api_key: str) -> tuple[float | None, float | None]:
    headers = {"Authorization": f"KakaoAK {api_key}"}
    params = {"query": address}
    try:
        response = requests.get(
            "https://dapi.kakao.com/v2/local/search/address.json",
            headers=headers,
            params=params,
            timeout=4,
        )
        response.raise_for_status()
        documents = response.json().get("documents", [])
    except Exception:
        return None, None

    if not documents:
        return None, None

    first = documents[0]
    return _to_float(first.get("y")), _to_float(first.get("x"))


def reverse_geocode_district_with_kakao(
    lat: float,
    lon: float,
    api_key: str,
) -> str | None:
    headers = {"Authorization": f"KakaoAK {api_key}"}
    params = {"x": lon, "y": lat}
    try:
        response = requests.get(
            "https://dapi.kakao.com/v2/local/geo/coord2address.json",
            headers=headers,
            params=params,
            timeout=4,
        )
        response.raise_for_status()
        documents = response.json().get("documents", [])
    except Exception:
        return None

    if not documents:
        return None

    address = documents[0].get("address") or {}
    return address.get("region_2depth_name")


def _child_place_from_api_item(item: dict[str, Any]) -> ChildPlace | None:
    lat = _first_float(
        item,
        ["latCrtsVl", "lat", "latitude", "위도", "la", "y", "LAT", "FCLTY_LA"],
    )
    lon = _first_float(
        item,
        ["lotCrtsVl", "lon", "lng", "longitude", "경도", "lo", "x", "LON", "FCLTY_LO"],
    )
    name = _first_text(
        item,
        ["시설명", "놀이시설명", "fcltyNm", "pfctNm", "facltNm", "name", "FCLTY_NM"],
        "어린이놀이시설",
    )
    address = _first_text(
        item,
        ["ronaAddr", "lotnoAddr", "주소", "도로명주소", "rdnmadr", "lnmadr", "addr", "address", "FCLTY_ADDR"],
        None,
    )
    detail_address = _first_text(item, ["ronaDaddr", "lotnoDaddr"], None)
    if address and detail_address:
        address = f"{address} {detail_address}".strip()

    district = _first_text(item, ["rgnCdNm", "시군구명", "sigunguNm", "sggNm", "district"], None)
    category = _first_text(item, ["instlPlaceCdNm", "시설구분", "시설종류"], "어린이놀이시설")

    return ChildPlace(
        name=name,
        category=category,
        source="child_play_facility_api",
        lat=lat,
        lon=lon,
        address=address,
        district=district,
        raw=item,
    )


def _is_operating_play_facility(item: dict[str, Any]) -> bool:
    operating = str(item.get("operYnCdNm") or item.get("operYnCd") or "").strip()
    closed = str(item.get("clsgYmd") or "").strip()
    return operating in {"", "운영", "B001"} and not closed


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for value in payload for item in _extract_items(value)]
    if not isinstance(payload, dict):
        return []

    items: list[dict[str, Any]] = []
    for key, value in payload.items():
        lowered = str(key).lower()
        if lowered in {"item", "items", "row", "rows"}:
            items.extend(_extract_items(value))
        elif isinstance(value, list):
            if all(isinstance(v, dict) for v in value):
                items.extend(value)
            else:
                items.extend(_extract_items(value))
        elif isinstance(value, dict):
            items.extend(_extract_items(value))

    return items


def _is_place_near(
    place: ChildPlace,
    center: tuple[float, float] | None,
    radius_m: float | None,
) -> bool:
    if center is None or radius_m is None or not place.has_coordinate:
        return True
    return _haversine_m(center[0], center[1], place.lat, place.lon) <= radius_m


def _is_seoul_place(place: ChildPlace) -> bool:
    text = " ".join(
        str(v)
        for v in [place.address, place.district, place.raw]
        if v is not None
    )
    return not text or "서울" in text


def _normalize_address(district: str, road_address: Any) -> str:
    address = str(road_address).strip()
    if "서울" in address:
        return address
    if district in address:
        return f"서울특별시 {address}"
    return f"서울특별시 {district} {address}"


def _first_float(item: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = item.get(key)
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return None


def _first_text(item: dict[str, Any], keys: list[str], default: str | None) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _read_child_protection_zone_rows(path: Path) -> list[dict[str, Any]]:
    rows = _read_xlsx_sheet(path, "어린이보호구역 지정현황")
    parsed: list[dict[str, Any]] = []

    for row in rows[6:]:
        district = _cell(row, 2)
        road_address = _cell(row, 4)
        name = _cell(row, 5)
        if not district or not road_address or not name:
            continue
        if district in {"합계", "소계"} or name == "시설명":
            continue

        parsed.append(
            {
                "district": district,
                "dong": _cell(row, 3),
                "road_address": road_address,
                "name": name,
                "facility_type": _cell(row, 6) or "어린이보호구역",
                "year": _cell(row, 7),
            }
        )

    return parsed


def _read_xlsx_sheet(path: Path, sheet_name: str) -> list[list[str | None]]:
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
    }

    with zipfile.ZipFile(path) as archive:
        shared_strings = _read_shared_strings(archive, ns)
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels.findall("pkg:Relationship", ns)
        }

        target: str | None = None
        for sheet in workbook.findall("main:sheets/main:sheet", ns):
            if sheet.attrib.get("name") == sheet_name:
                rel_id = sheet.attrib.get(f"{{{ns['rel']}}}id")
                target = rel_targets.get(rel_id or "")
                break

        if target is None:
            return []

        sheet_path = "xl/" + target.lstrip("/")
        xml = ElementTree.fromstring(archive.read(sheet_path))

    result: list[list[str | None]] = []
    for row in xml.findall("main:sheetData/main:row", ns):
        values: list[str | None] = []
        for cell in row.findall("main:c", ns):
            col_index = _excel_column_index(cell.attrib.get("r", "A1"))
            while len(values) <= col_index:
                values.append(None)
            values[col_index] = _read_xlsx_cell(cell, shared_strings, ns)
        result.append(values)

    return result


def _read_shared_strings(
    archive: zipfile.ZipFile,
    ns: dict[str, str],
) -> list[str]:
    try:
        xml = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []

    strings: list[str] = []
    for item in xml.findall("main:si", ns):
        parts = [text.text or "" for text in item.findall(".//main:t", ns)]
        strings.append("".join(parts))
    return strings


def _read_xlsx_cell(
    cell: ElementTree.Element,
    shared_strings: list[str],
    ns: dict[str, str],
) -> str | None:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        text = cell.find(".//main:t", ns)
        return (text.text or "").strip() if text is not None else None

    value = cell.find("main:v", ns)
    if value is None or value.text is None:
        return None

    raw = value.text.strip()
    if cell_type == "s":
        index = int(raw)
        return shared_strings[index].strip() if index < len(shared_strings) else None
    return raw


def _excel_column_index(cell_ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", cell_ref.upper())
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter) - ord("A") + 1
    return max(index - 1, 0)


def _cell(row: list[str | None], index: int) -> str | None:
    if index >= len(row) or row[index] is None:
        return None
    value = str(row[index]).strip()
    return value or None
