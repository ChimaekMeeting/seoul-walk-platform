class StringConverter:
    def __init__(self):
        self.mapped_keyword = {
            "place_address": "주소",
            "place_name": "장소명",
            "place_lat": "위도",
            "place_lon": "경도"
        }

    def dict_to_str(self, data: dict) -> str:
        data_str = ""
        for key, value in data.items():
            data_str += f"{self.mapped_keyword.get(key)}: {value}\n"
        
        return data_str

    def list_to_str(self, data: list) -> str:
        data_str = ""
        for idx, d in enumerate(data, start=1):
            data_str += f"후보{idx}\n"
            for key, value in d.items():
                data_str += f"{self.mapped_keyword.get(key)}: {value}\n"
            data_str += "\n"
        
        return data_str