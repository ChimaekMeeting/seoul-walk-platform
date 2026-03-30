from langchain_core.output_parsers import JsonOutputParser
import asyncio

class LocationSearcher:
    def __init__(self, gpt_client, kakao_client):
        self.gpt_client = gpt_client
        self.kakao_client = kakao_client
        self.parser = JsonOutputParser()

        # 정확한 위치를 알아내기 위해 호출해야 하는 함수 목록
        self.function_map = {
            "get_address_from_keyword": self.kakao_client.get_address_from_keyword,
            "get_address_from_category": self.kakao_client.get_address_from_category
        }

    async def get_response(self, location_text: str):
        """
        정확한 위치를 파악하기 위한 function calling을 진행합니다.
        """
        print(f"location_text: {location_text}")
        return await self.gpt_client.get_response(
            prompt_name="location_selection",
            input_data={
                "location_text": location_text,
                "format_instructions": self.parser.get_format_instructions()
            },
            output_parser=self.parser
        )
    
    async def get_place_info(self, function, query: str, lat: float, lon: float):
        """
        출발지와 목적지의 정확한 위치를 파악합니다.
        """
        print(function, query)
        response = await function(query, lat, lon)
        documents = response.get("documents")
        MAX_RANGE = min(3, len(documents))

        results = []
        for i in range(MAX_RANGE):
            results.append({
                "place_address": documents[i].get("address_name"),
                "place_name": documents[i].get("place_name"),
                "place_lat": documents[i].get("y"),
                "place_lon": documents[i].get("x")
            })

        return results

    async def run(self, context: dict, lat: float, lon: float):
        """
        수집된 정보를 기반으로 출발지와 목적지의 정확한 위치를 파악합니다.
        """
        is_circular = context.get("is_circular")
        origin = context.get("origin")
        destination = origin if is_circular else context.get("destination")

        # 순환
        if is_circular:
            origin_location = await self.get_response(origin)
        # 편도
        else:
            origin_location, destination_location = await asyncio.gather(
                self.get_response(origin),
                self.get_response(destination)
            )

        # 함수 매핑
        origin_function = self.function_map.get(origin_location.get("function"))
        origin_query = origin_location.get("query")
        if not is_circular:
            destination_function = self.function_map.get(destination_location.get("function"))
            destination_query = destination_location.get("query")

        # 출발지가 현 지점인 경우
        is_here = origin_location.get("is_here")

        # 순환 & 출발지가 현 지점인 경우
        if is_circular and is_here:
            origin_location = await self.kakao_client.get_address_from_coords(lat, lon)
            destination_location = origin_location
        # 순환 & 출발지가 다른 장소인 경우
        elif is_circular and not is_here:
            origin_location = await self.get_place_info(origin_function, origin_query, lat, lon)
            destination_location = origin_location
        # 편도 & 출발지가 현 지점인 경우
        elif not is_circular and is_here:
            origin_location, destination_location = await asyncio.gather(
                self.kakao_client.get_address_from_coords(lat, lon),
                self.get_place_info(destination_function, destination_query, lat, lon)
            )
        # 편도 & 출발지가 다른 장소인 경우
        else:
            origin_location, destination_location = await asyncio.gather(
                self.get_place_info(origin_function, origin_query, lat, lon),
                self.get_place_info(destination_function, destination_query, lat, lon)
            )

        return {
            "is_circular": is_circular,
            "origin_location": origin_location,
            "destination_location": destination_location
        }