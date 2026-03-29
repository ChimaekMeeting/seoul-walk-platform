from langchain_core.output_parsers import JsonOutputParser
import asyncio

# 경위도까지 모두 포함했을 때, 다음 노드로 넘어가도록 해야 함.

class LocationRouter:
    def __init__(self, gpt_client, string_converter):
        self.gpt_client = gpt_client
        self.string_converter = string_converter
        self.parser = JsonOutputParser()

    async def get_response(self, user_prompt: str, context: dict, location: str, location_candidate: str):
        """
        위치를 결정합니다.
        """
        return await self.gpt_client.get_response(
            prompt_name="location_routing",
            input_data={
                "user_prompt": user_prompt,
                "context": context,
                "location": location,
                "location_candidate": location_candidate,
                "format_instructions": self.parser.get_format_instructions()
            },
            output_parser=self.parser
        )
    
    async def run(self, user_prompt: str, context: dict, origin_candidate, destination_candidate):
        """
        출발지와 목적지를 최종적으로 결정합니다.
        """
        origin_candidate_str = self.string_converter.dict_to_str(origin_candidate) if isinstance(origin_candidate, dict) else self.string_converter.list_to_str(origin_candidate)

        print("출발지 후보")
        print(origin_candidate_str)

        origin_task = self.get_response(
            user_prompt,
            context,
            "출발지",
            origin_candidate_str
        )

        if context.get("is_circular"):
            origin_res = await origin_task
            return origin_res, origin_res
        
        destination_candidate_str = self.string_converter.dict_to_str(destination_candidate) if isinstance(destination_candidate, dict) else self.string_converter.list_to_str(destination_candidate)
        print("목적지 후보")
        print(destination_candidate_str)
        
        destination_task = self.get_response(
            user_prompt,
            context,
            "목적지",
            destination_candidate_str
        )
        return await asyncio.gather(origin_task, destination_task)