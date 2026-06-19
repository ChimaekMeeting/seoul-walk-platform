import pandas as pd

from src.repository.raw.csv_raw_repository import CsvRawRepository


class CSVSource:
    TAGS: list[tuple[str, str]] = [
        ("type", "protection_zone"),
        ("type", "streetlight"),
        ("type", "bike_road"),
        ("type", "cctv"),
        ("type", "running_park"),
    ]

    def __init__(self, raw_dir: str = "src/data/raw"):
        self.raw_dir = raw_dir

    # ── 공통 모듈 ──────────────────────────────────────────────

    def fetch_and_store(self, key: str, value: str) -> None:
        """단일 데이터셋을 파일에서 읽어 DB에 저장합니다. 이미 저장된 경우 스킵합니다."""
        query_key = f"{key}={value}"
        if CsvRawRepository.exists(query_key):
            return

        df, lat_col, lon_col, name_col, city_col = self._fetch_all(value)
        df = self.clean(df, cols=list(df.columns), lat_col=lat_col,
                        lon_col=lon_col, city_col=city_col)
        CsvRawRepository.save_dataframe(df, query_key,
                                        lat_col=lat_col, lon_col=lon_col, name_col=name_col)

    def store(self) -> None:
        """TAGS의 모든 데이터셋을 DB에 저장합니다."""
        for key, value in self.TAGS:
            self.fetch_and_store(key, value)

    def get(self, key: str, value: str):
        """DB에서 데이터를 조회합니다. DB에 없으면 파일에서 읽어 저장합니다."""
        query_key = f"{key}={value}"
        if not CsvRawRepository.exists(query_key):
            self.fetch_and_store(key, value)
        return CsvRawRepository.get(query_key)

    def clean(
        self,
        df: pd.DataFrame,
        cols: list[str],
        lat_col: str,
        lon_col: str,
        city_col: str | None = None,
        city_value: str = "서울",
    ) -> pd.DataFrame:
        """기본 전처리를 수행합니다. 위경도 결측·중복만 제거합니다."""
        existing = [c for c in cols if c in df.columns]
        df = df[existing].copy()

        df = df.dropna(subset=[lat_col, lon_col])
        df = df[~df[[lat_col, lon_col]].isin(["", "null"]).any(axis=1)]

        if city_col and city_col in df.columns:
            df = df[df[city_col].str.contains(city_value, na=False)]

        df = df.drop_duplicates(subset=[lat_col, lon_col])
        return df.reset_index(drop=True)

    # ── 단순 파일 로더 (DB 저장 없음) ─────────────────────────

    def load_walk_network(self) -> pd.DataFrame:
        """도보 네트워크 CSV를 반환합니다. WKT 링크 데이터라 DB 저장 없이 직접 사용합니다."""
        return self._read_csv("서울시 자치구별 도보 네트워크 공간정보.csv")

    def load_landmark_sheet(self, url: str) -> pd.DataFrame:
        """Google Sheets CSV URL에서 랜드마크 시트를 반환합니다."""
        return pd.read_csv(url)

    # ── 내부 수집 로직 ─────────────────────────────────────────

    def _fetch_all(self, value: str) -> tuple[pd.DataFrame, str, str, str | None, str | None]:
        """
        데이터셋 value에 따라 수집 메서드를 디스패치합니다.

        Returns:
            (df, lat_col, lon_col, name_col, city_col)
        """
        dispatch = {
            "protection_zone": self._load_protection_zone,
            "streetlight":     self._load_streetlight,
            "bike_road":       self._load_bike_road,
            "cctv":            self._load_cctv,
            "running_park":    self._load_running_park,
        }
        if value not in dispatch:
            raise NotImplementedError(f"'{value}' 데이터셋 미구현")
        return dispatch[value]()

    def _read_csv(self, filename: str) -> pd.DataFrame:
        path = f"{self.raw_dir}/{filename}"
        try:
            return pd.read_csv(path, encoding="cp949")
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="utf-8")

    def _find_col(self, df: pd.DataFrame, candidates: list[str]) -> str | None:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    def _load_protection_zone(self) -> tuple[pd.DataFrame, str, str, str, str]:
        df = self._read_csv("전국어린이보호구역표준데이터.csv")
        return df, "위도", "경도", "대상시설명", "소재지도로명주소"

    def _load_streetlight(self) -> tuple[pd.DataFrame, str, str, None, str]:
        df = self._read_csv("전국스마트가로등표준데이터.csv")
        return df, "위도", "경도", None, "시도명"

    def _load_bike_road(self) -> tuple[pd.DataFrame, str, str, str | None, None]:
        df = self._read_csv("서울시 자전거도로.csv")
        df.columns = [str(c).strip() for c in df.columns]

        lat_col  = self._find_col(df, ["기점위도", "시작위도", "출발위도", "Y좌표시작(WGS84)", "START_LAT"])
        lon_col  = self._find_col(df, ["기점경도", "시작경도", "출발경도", "X좌표시작(WGS84)", "START_LNG"])
        name_col = self._find_col(df, ["노선명", "구간명", "자전거도로명", "시설명"])

        if not lat_col or not lon_col:
            raise ValueError(f"자전거도로 CSV에서 위경도 컬럼을 찾을 수 없습니다. 컬럼: {list(df.columns)}")

        return df, lat_col, lon_col, name_col, None

    def _load_cctv(self) -> tuple[pd.DataFrame, str, str, None, None]:
        df = pd.read_excel(f"{self.raw_dir}/서울시CCTV정보.xlsx")
        return df, "WGS84위도", "WGS84경도", None, None

    def _load_running_park(self) -> tuple[pd.DataFrame, str, str, str, None]:
        df = pd.read_excel(f"{self.raw_dir}/서울시 주요 공원현황.xlsx", header=1)
        df.columns = [str(c).strip() for c in df.columns]
        return df, "Y좌표(WGS84)", "X좌표(WGS84)", "공원명", None
