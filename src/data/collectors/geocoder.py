import os
import requests
import pandas as pd
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")

def get_lat_lng_from_kakao(address: str):
    """
    카카오 로컬 API를 사용하여 주소를 위도, 경도로 변환합니다.
    """
    if not KAKAO_REST_API_KEY:
        print("❌ .env 파일에 KAKAO_REST_API_KEY가 설정되어 있지 않습니다.")
        return None, None

    if not address or pd.isna(address):
        return None, None

    url = f"https://dapi.kakao.com/v2/local/search/address.json?query={address}"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
    
    try:
        response = requests.get(url, headers=headers).json()
        if response.get('documents'):
            lon = float(response['documents'][0]['x']) # 경도
            lat = float(response['documents'][0]['y']) # 위도
            return lat, lon
        else:
            return None, None
    except Exception as e:
        print(f"주소 변환 오류 ({address}): {e}")
        return None, None

def geocode_excel_file(input_excel_path: str, address_col: str, output_csv_path: str):
    """
    엑셀 파일을 읽어 특정 주소 컬럼의 위경도를 추가한 뒤 CSV로 저장합니다.
    """
    print(f"[{input_excel_path}] 파일을 읽어 위경도 변환을 시작합니다...")
    
    try:
        df = pd.read_excel(input_excel_path)
    except Exception as e:
        print(f"❌ 엑셀 파일을 읽는 중 오류가 발생했습니다: {e}")
        return
    
    if address_col not in df.columns:
        print(f"❌ '{address_col}' 컬럼이 파일에 존재하지 않습니다. 컬럼명을 확인해주세요.")
        return

    lat_list = []
    lon_list = []

    total = len(df)
    for i, row in df.iterrows():
        address = str(row[address_col]).strip()
        lat, lon = get_lat_lng_from_kakao(address)
        lat_list.append(lat)
        lon_list.append(lon)
        
        # 100건마다 진행 상황 출력
        if (i+1) % 100 == 0:
            print(f"진행 상황: {i+1} / {total} 완료")

    df['위도'] = lat_list
    df['경도'] = lon_list
    
    failed = df['위도'].isna().sum()
    print(f"✅ 변환 완료: 전체 {total}건 중 {total - failed}건 성공 (실패 {failed}건)")
    
    df.to_csv(output_csv_path, index=False, encoding='utf-8-sig')
    print(f"💾 결과가 [{output_csv_path}]에 저장되었습니다.")

if __name__ == "__main__":
    # 💡 사용 예시:
    # 1. 터미널에서 `pip install requests pandas openpyxl python-dotenv` 설치 확인
    # 2. .env 파일에 KAKAO_REST_API_KEY=자신의카카오API키 입력
    # 3. 아래 주석을 풀고 파일 경로를 맞춰서 실행하세요.
    
    # geocode_excel_file(
    #     input_excel_path="src/data/raw/서울특별시 안심지킴이집 정보_20180521.xlsx", 
    #     address_col="주소", 
    #     output_csv_path="src/data/raw/안심지킴이집_좌표포함.csv"
    # )
    pass
