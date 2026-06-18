import pandas as pd


class CSVSource:
    def __init__(self, raw_dir: str = "src/data/raw"):
        self.raw_dir = raw_dir

    def clean(
        self,
        df: pd.DataFrame,
        cols: list[str],
        lat_col: str,
        lon_col: str,
        city_col: str | None = None,
        city_value: str = "서울",
    ) -> pd.DataFrame:
        """
        기본 전처리를 수행합니다.
        """
        # 주요 컬럼 추출
        existing = [c for c in cols if c in df.columns]
        df = df[existing].copy()

        # 결측치 제거
        df = df.dropna(subset=existing)
        df = df[~df[existing].isin(["", "null"]).any(axis=1)]

        # 서울 필터링
        if city_col and city_col in df.columns:
            df = df[df[city_col].str.contains(city_value, na=False)]

        # 경위도 중복 데이터 제거
        df = df.drop_duplicates(subset=[lat_col, lon_col])

        return df.reset_index(drop=True)
