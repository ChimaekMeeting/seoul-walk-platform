import pandas as pd

from src.data.utils.geocode_utils import Geocoder
from src.repository.raw.csv_raw_repository import CsvRawRepository


class CSVSource:
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
        """
        단일 데이터셋을 파일에서 읽어 DB에 저장합니다. 이미 저장된 경우 스킵합니다.
        """
        print(f"{value} 데이터를 적재합니다")
        query_key = f"{key}={value}"
        if CsvRawRepository.exists(query_key):
            return

        # 수집
        df, lat_col, lon_col, name_col, addr_col, city_col, end_lat_col, end_lon_col = self._fetch_all(value)

        # 전처리
        df = self.clean(
            df,
            lat_col=lat_col, lon_col=lon_col,
            name_col=name_col, addr_col=addr_col,
            city_col=city_col,
            end_lat_col=end_lat_col, end_lon_col=end_lon_col,
        )

        # 저장
        CsvRawRepository.save(df, query_key)

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

        # 경위도 중복 데이터 제거
        df = df.drop_duplicates(subset=[lat_col, lon_col])

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
        """
        df = self._read_csv("전국어린이보호구역표준데이터.csv")
        cols = ["위도", "경도", "대상시설명", "소재지지번주소", "시설종류", "CCTV설치여부", "CCTV설치대수"]
        df = df[[c for c in cols if c in df.columns]]
        #           lat,   lon,      name,         addr,          city,          end
        return df, "위도", "경도", "대상시설명", "소재지지번주소", "소재지지번주소", None, None

    def _load_streetlight(self):
        """
        스마트가로등 데이터를 로드합니다.
        """
        df = self._read_csv("전국스마트가로등표준데이터.csv")
        cols = ["위도", "경도", "시도명", "소재지지번주소", "위급상황신고가능여부"]
        df = df[[c for c in cols if c in df.columns]]
        #           lat,   lon,   name,     addr,        city,    end
        return df, "위도", "경도", None, "소재지지번주소", "시도명", None, None

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
        """
        df = self._read_excel("서울시CCTV정보.xlsx")
        cols = ["WGS84위도", "WGS84경도", "소재지지번주소", "카메라대수", "보관일수", "관리기관전화번호"]
        df = df[[c for c in cols if c in df.columns]]
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
        공중화장실 데이터를 로드합니다.
        위경도 컬럼이 없어 소재지도로명주소를 카카오 주소 검색으로 좌표 변환합니다.
        """
        df = self._read_csv("공중화장실정보_서울특별시.csv")
        cols = ["화장실명", "소재지도로명주소", "소재지지번주소", "개방시간", "비상벨설치여부", "기저귀교환대유무"]
        df = df[[c for c in cols if c in df.columns]]
        df = df.dropna(subset=["소재지도로명주소"])

        geocoder = Geocoder()
        coords = geocoder.geocode_place_names(df["소재지도로명주소"].tolist())
        df["위도"] = [c[0] for c in coords]
        df["경도"] = [c[1] for c in coords]
        df = df.dropna(subset=["위도", "경도"])
        return df, "위도", "경도", "화장실명", "소재지도로명주소", None, None, None

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
        """
        df = self._read_csv("전국가로수길정보표준데이터.csv")
        cols = ["가로수길시작위도", "가로수길시작경도", "가로수길종료위도", "가로수길종료경도", "가로수길명", "제공기관명"]
        df = df[[c for c in cols if c in df.columns]]
        return df, "가로수길시작위도", "가로수길시작경도", "가로수길명", None, "제공기관명", "가로수길종료위도", "가로수길종료경도"
