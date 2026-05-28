import asyncio
import pandas as pd

from src.infrastructure.external.client.kakao_client import KakaoClient

class Geocoder:
    """
    카카오 로컬 API를 사용하여 주소를 위경도 좌표로 변환합니다.
    """

    def __init__(self):
        self.client = KakaoClient()

    async def _geocode_all(
        self, addresses: list[str]
    ) -> list[tuple[float | None, float | None]]:
        """
        주소 목록을 순차적으로 지오코딩하여 (위도, 경도) 튜플 목록을 반환합니다.
        """
        results = []
        for address in addresses:
            if not address or (isinstance(address, float) and pd.isna(address)):
                results.append((None, None))
                continue
            try:
                result = await self.client.get_kakao_geocode(address)
                if result:
                    lon, lat = result
                    results.append((lat, lon))
                else:
                    results.append((None, None))
            except Exception as e:
                print(f"주소 변환 오류 ({address}): {e}")
                results.append((None, None))
        return results

    def get_lat_lng(self, address: str) -> tuple[float | None, float | None]:
        """
        단일 주소를 (위도, 경도) 튜플로 변환합니다.
        """
        if not address or (isinstance(address, float) and pd.isna(address)):
            return None, None
        return asyncio.run(self._geocode_all([address]))[0]

    def geocode_excel_file(
        self, input_excel_path: str, address_col: str, output_csv_path: str
    ) -> None:
        """
        엑셀 파일의 주소 컬럼을 위경도로 변환하여 CSV로 저장합니다.
        """
        try:
            df = pd.read_excel(input_excel_path)
        except Exception as e:
            print(f"❌ 파일 읽기 오류: {e}")
            return

        if address_col not in df.columns:
            print(f"❌ '{address_col}' 컬럼이 없습니다.")
            return

        addresses = [str(row).strip() for row in df[address_col]]
        coords = asyncio.run(self._geocode_all(addresses))

        df["위도"] = [c[0] for c in coords]
        df["경도"] = [c[1] for c in coords]

        failed = df["위도"].isna().sum()
        total = len(df)
        print(f"✅ 변환 완료: {total}건 중 {total - failed}건 성공 ({failed}건 실패)")

        df.to_csv(output_csv_path, index=False, encoding="utf-8-sig")
        print(f"💾 [{output_csv_path}]에 저장되었습니다.")
