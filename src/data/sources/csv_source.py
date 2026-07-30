import logging

import pandas as pd

from src.data.utils.geocode_utils import Geocoder
from src.repository.raw.csv_raw_repository import CsvRawRepository

logger = logging.getLogger(__name__)


class CSVSource:
    STREETLIGHT_LOCATION_CORRECTIONS: dict[str, tuple[float, float]] = {
        "서울특별시 구로구 개봉로 8": (37.486348662469, 126.85684038742),
        "서울특별시 구로구 구로동로 34": (37.4846965004551, 126.886558766573),
    }

    CCTV_LOCATION_CORRECTIONS: dict[int, tuple[float, float]] = {
        5126: (37.5979406633024, 127.03548801176),
        5127: (37.597802551937, 127.037209042531),
        5375: (37.6125190746253, 127.042228458857),
        5458: (37.611670891768, 127.039606498096),
        5463: (37.6199572968278, 127.053895394039),
        5823: (37.6131691854541, 127.017457223186),
        5953: (37.5986363173449, 126.994889082557),
        19223: (37.6648983029005, 127.034998844885),
        21101: (37.6529595368941, 127.0298914081),
        21102: (37.6529595368941, 127.0298914081),
        26180: (37.5951568662331, 127.006933625102),
        26181: (37.6039356030352, 127.000568045827),
        26182: (37.6039356030352, 127.000568045827),
        28323: (37.5615987374058, 126.982169090151),
    }

    TOILET_LOCATION_CORRECTIONS: dict[int, dict[str, object]] = {
        266601: {
            "도로명주소": "서울특별시 중구 충무로 56-1",
            "x 좌표": 126.992848341729,
            "y 좌표": 37.5661815238113,
        },
        266704: {
            "도로명주소": "서울특별시 중구 충무로 11",
            "x 좌표": 126.992912675198,
            "y 좌표": 37.5621562365797,
        },
    }

    TAGS: list[tuple[str, str]] = [
        ("type", "protection_zone"),
        ("type", "streetlight"),
        ("type", "bike_road"),
        ("type", "bike_road_seoul"),
        ("type", "cctv"),
        ("type", "running_park"),
        ("type", "street_tree"),
        ("type", "seoul_trail"),
        ("type", "toilet"),
        ("type", "bus_stop"),
        ("type", "commercial"),
    ]

    def __init__(self, raw_dir: str = "src/data/raw"):
        self.raw_dir = raw_dir

    def fetch_and_store(self, key: str, value: str) -> None:
        query_key = f"{key}={value}"
        if CsvRawRepository.exists(query_key):
            logger.debug("%s 이미 적재됨, 스킵", query_key)
            return

        logger.info("%s 파일 로드 시작", value)
        # 수집
        df, lat_col, lon_col, name_col, addr_col, city_col, end_lat_col, end_lon_col = self._fetch_all(value)
        logger.debug("%s 원본 %d행", value, len(df))

        # 전처리
        df = self.clean(
            df,
            lat_col=lat_col, lon_col=lon_col,
            name_col=name_col, addr_col=addr_col,
            city_col=city_col,
            end_lat_col=end_lat_col, end_lon_col=end_lon_col,
        )
        logger.debug("%s 전처리 후 %d행", value, len(df))

        # 저장
        CsvRawRepository.save(df, query_key)
        logger.info("%s 적재 완료: %d행", value, len(df))

    def store(self) -> None:
        """
        모든 데이터셋을 DB에 저장합니다.
        """
        for key, value in self.TAGS:
            self.fetch_and_store(key, value)

    def get(self, key: str, value: str):
        """
        DB에서 데이터를 조회합니다. 없으면 파일에서 읽어 저장합니다.
        """
        query_key = f"{key}={value}"
        if not CsvRawRepository.exists(query_key):
            self.fetch_and_store(key, value)
        return CsvRawRepository.get(query_key)

    def clean(
        self,
        df: pd.DataFrame,
        lat_col: str,
        lon_col: str,
        name_col: str | None = None,
        addr_col: str | None = None,
        city_col: str | None = None,
        city_value: str = "서울",
        end_lat_col: str | None = None,
        end_lon_col: str | None = None,
    ) -> pd.DataFrame:
        """
        전처리를 수행합니다.
        """
        # 결측치 제거
        df = df.dropna(subset=[lat_col, lon_col])
        df = df[~df[[lat_col, lon_col]].isin(["", "null"]).any(axis=1)]

        # 서울 필터링
        if city_col and city_col in df.columns:
            df = df[df[city_col].str.contains(city_value, na=False)]

        # 같은 위치에 서로 다른 시설·센서가 있을 수 있으므로 RAW 단계에서는
        # 좌표 중복을 제거하지 않는다. 위치 단위 집계는 각 Layer collector가 맡는다.

        # 컬럼명 수정
        rename_map = {lat_col: "lat", lon_col: "lon"}
        if name_col:
            rename_map[name_col] = "name"
        if addr_col:
            rename_map[addr_col] = "address"
        if end_lat_col:
            rename_map[end_lat_col] = "end_lat"
            rename_map[end_lon_col] = "end_lon"
        df = df.rename(columns=rename_map)

        return df.reset_index(drop=True)

    def _read_csv(self, filename: str) -> pd.DataFrame:
        """
        CSV 파일을 로드합니다.
        """
        path = f"{self.raw_dir}/{filename}"
        try:
            return pd.read_csv(path, encoding="cp949")
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="utf-8")

    def _read_excel(self, filename: str, **kwargs) -> pd.DataFrame:
        """
        xlsx 파일을 로드합니다.
        """
        path = f"{self.raw_dir}/{filename}"
        return pd.read_excel(path, engine="openpyxl", **kwargs)

    def _fetch_all(self, value: str):
        """
        value에 따라 로드 메서드를 디스패치합니다.
        """
        dispatch = {
            "protection_zone": self._load_protection_zone,
            "streetlight":     self._load_streetlight,
            "bike_road":       self._load_bike_road,
            "bike_road_seoul": self._load_bike_road_seoul,
            "cctv":            self._load_cctv,
            "running_park":    self._load_running_park,
            "street_tree":       self._load_street_tree,
            "seoul_trail":       self._load_seoul_trail,
            "toilet":      self._load_toilet,
            "bus_stop":    self._load_bus_stop,
            "commercial":  self._load_commercial,
        }
        if value not in dispatch:
            raise NotImplementedError(f"'{value}' 데이터셋 미구현")
        return dispatch[value]()

    def load_walk_network(self) -> pd.DataFrame:
        """
        도보 네트워크 CSV를 반환합니다. WKT 링크 데이터라 DB 저장 없이 직접 사용합니다.
        """
        return self._read_csv("서울시 자치구별 도보 네트워크 공간정보.csv")

    def _load_protection_zone(self):
        """
        어린이보호구역 데이터를 로드합니다.

        도로명주소가 '서울특별시'로 시작하는 행만 사용합니다. 단순 포함
        검색은 경기도 시흥시 '서울대학로' 같은 다른 지역을 포함할 수 있습니다.
        """
        df = self._read_csv("전국어린이보호구역표준데이터.csv")
        df = df[
            df["소재지도로명주소"]
            .astype("string")
            .str.strip()
            .str.startswith("서울특별시", na=False)
        ]
        #           lat,   lon,      name,         addr,          city,          end
        return df, "위도", "경도", "대상시설명", "소재지도로명주소", None, None, None

    def _load_streetlight(self):
        """
        스마트가로등 데이터를 로드합니다.

        서로 다른 서울 주소가 동일 좌표로 제공된 사례 중 주소 검색으로 오류가
        확인된 2건을 교정합니다. 같은 위치의 서로 다른 센서 행은 보존합니다.
        """
        df = self._read_csv("전국스마트가로등표준데이터.csv")

        for address, (lat, lon) in self.STREETLIGHT_LOCATION_CORRECTIONS.items():
            row_mask = df["소재지도로명주소"].eq(address)
            if not row_mask.any():
                logger.warning("스마트가로등 위치 정정 대상 주소를 찾지 못했습니다: %s", address)
                continue
            df.loc[row_mask, "위도"] = lat
            df.loc[row_mask, "경도"] = lon

        #           lat,   lon,   name,     addr,        city,    end
        return df, "위도", "경도", None, "소재지도로명주소", "시도명", None, None

    def _load_bike_road(self):
        """
        자전거도로 데이터를 로드합니다. 기점·종점 좌표로 LINESTRING을 구성합니다.
        """
        df = self._read_csv("전국자전거도로표준데이터.csv")
        cols = [c for c in ["기점위도", "기점경도", "종점위도", "종점경도", "시도명", "노선명", "자전거도로종류", "총길이(km)"] if c]
        df = df[[c for c in cols if c in df.columns]]
        #             lat,      lon,      name,  addr,   city,           end
        return df, "기점위도", "기점경도", "노선명", None, "시도명", "종점위도", "종점경도"

    def _load_cctv(self):
        """
        CCTV 데이터를 로드합니다.

        서울 주소인데 좌표가 서울 밖이거나 유효 범위를 벗어난 14건을
        번호 기준으로 검증된 주소 검색 좌표로 교정합니다.
        """
        df = self._read_excel("서울시CCTV정보.xlsx")

        for number, (lat, lon) in self.CCTV_LOCATION_CORRECTIONS.items():
            row_mask = pd.to_numeric(df["번호"], errors="coerce").eq(number)
            if not row_mask.any():
                logger.warning("CCTV 위치 정정 대상 번호 %s을 찾지 못했습니다.", number)
                continue
            df.loc[row_mask, "WGS84위도"] = lat
            df.loc[row_mask, "WGS84경도"] = lon

        #             lat,         lon,     name,     addr,       city,    end
        return df, "WGS84위도", "WGS84경도", None, "소재지지번주소", None, None, None

    def _load_bike_road_seoul(self):
        """
        서울시 자전거도로 데이터를 로드합니다. 기점·종점 좌표로 LINESTRING을 구성합니다.
        """
        df = self._read_csv("서울시_자전거도로.csv")
        cols = ["기점위도", "기점경도", "종점위도", "종점경도", "시도명", "노선명", "자전거도로종류", "총길이(km)"]
        df = df[[c for c in cols if c in df.columns]]
        return df, "기점위도", "기점경도", "노선명", None, "시도명", "종점위도", "종점경도"

    def _load_running_park(self):
        """
        주요 공원 데이터를 로드합니다.
        """
        df = self._read_csv("서울시 주요 공원현황.csv")
        cols = ["Y좌표(WGS84)", "X좌표(WGS84)", "공원명", "공원주소", "공원개요", "면적", "주요시설", "주요식물", "안내도", "오시는길", "이용시참고사항", "전화번호", "바로가기"]
        df = df[[c for c in cols if c in df.columns]]
        #             lat,             lon,        name,    addr,    city,    end
        return df, "Y좌표(WGS84)", "X좌표(WGS84)", "공원명", "공원주소", None, None, None

    def _load_seoul_trail(self):
        """
        서울 둘레길 데이터를 로드합니다.
        시작/종료 위치가 장소명 텍스트이므로 카카오 키워드 검색으로 좌표를 변환합니다.
        """
        df = self._read_csv("서울 둘레길.csv")
        geocoder = Geocoder()

        start_coords = geocoder.geocode_place_names(df["시작 위치"].tolist())
        end_coords   = geocoder.geocode_place_names(df["종료 위치"].tolist())

        df["시작위도"] = [c[0] for c in start_coords]
        df["시작경도"] = [c[1] for c in start_coords]
        df["종료위도"] = [c[0] for c in end_coords]
        df["종료경도"] = [c[1] for c in end_coords]

        df = df.dropna(subset=["시작위도", "시작경도", "종료위도", "종료경도"])
        return df, "시작위도", "시작경도", "둘레길 명", None, None, "종료위도", "종료경도"

    def _load_toilet(self):
        """
        좌표가 포함된 서울시 공중화장실 위치정보를 로드합니다.

        원본에서 서울 중구 시설 2건의 주소와 좌표가 대전 중구로 잘못
        제공되므로 연번을 기준으로 검증된 서울 주소·좌표를 적용합니다.
        원본 파일은 수정하지 않습니다.
        """
        df = self._read_csv("서울시 공중화장실 위치정보.csv")

        serials = pd.to_numeric(df["연번"], errors="coerce")
        for serial, corrections in self.TOILET_LOCATION_CORRECTIONS.items():
            row_mask = serials.eq(serial)
            if not row_mask.any():
                logger.warning("화장실 위치 정정 대상 연번 %s을 찾지 못했습니다.", serial)
                continue
            for column, value in corrections.items():
                df.loc[row_mask, column] = value

        cols = [
            "연번",
            "건물명",
            "도로명주소",
            "지번주소",
            "x 좌표",
            "y 좌표",
            "구 명칭",
            "유형",
            "개방시간",
            "장애인화장실 현황",
            "편의시설 (기타설비)",
        ]
        df = df[[c for c in cols if c in df.columns]]
        return df, "y 좌표", "x 좌표", "건물명", "도로명주소", None, None, None

    def _load_bus_stop(self):
        """
        서울시 버스 정류소 데이터를 로드합니다.
        X좌표=경도, Y좌표=위도입니다.
        """
        df = self._read_csv("서울시 버스정류소 위치정보.csv")
        cols = ["정류소명", "정류소번호", "X좌표", "Y좌표", "정류소 타입"]
        df = df[[c for c in cols if c in df.columns]]
        return df, "Y좌표", "X좌표", "정류소명", None, None, None, None

    def _load_commercial(self):
        """
        소상공인 상가(상권) 정보를 로드합니다.
        """
        df = self._read_csv("소상공인시장진흥공단_상가(상권)정보_서울_202603.csv")
        cols = ["상호명", "도로명주소", "경도", "위도", "상권업종대분류명", "상권업종중분류명", "상권업종소분류명", "시도명"]
        df = df[[c for c in cols if c in df.columns]]
        return df, "위도", "경도", "상호명", "도로명주소", "시도명", None, None

    def _load_street_tree(self):
        """
        가로수길 데이터를 로드합니다. 기점·종점 좌표로 LINESTRING을 구성합니다.

        서울 제공기관의 원본 819건 중 양 끝 좌표가 서울 범위에 있고
        시작·종료점이 다른 747건만 공간 입력으로 사용합니다. 제외 행은
        원본 파일에 그대로 보존합니다.
        """
        df = self._read_csv("전국가로수길정보표준데이터.csv")
        provider_mask = (
            df["제공기관명"]
            .astype("string")
            .str.strip()
            .str.startswith("서울특별시", na=False)
        )
        start_lat = pd.to_numeric(df["가로수길시작위도"], errors="coerce")
        start_lon = pd.to_numeric(df["가로수길시작경도"], errors="coerce")
        end_lat = pd.to_numeric(df["가로수길종료위도"], errors="coerce")
        end_lon = pd.to_numeric(df["가로수길종료경도"], errors="coerce")
        start_in_seoul = start_lat.between(37.40, 37.72) & start_lon.between(126.75, 127.22)
        end_in_seoul = end_lat.between(37.40, 37.72) & end_lon.between(126.75, 127.22)
        nonzero_line = ~(
            start_lat.eq(end_lat)
            & start_lon.eq(end_lon)
        )
        df = df[provider_mask & start_in_seoul & end_in_seoul & nonzero_line]

        return (
            df,
            "가로수길시작위도",
            "가로수길시작경도",
            "가로수길명",
            None,
            None,
            "가로수길종료위도",
            "가로수길종료경도",
        )
