import httpx

class WeatherAPITester:
    def __init__(self):
        self.base_url = "http://localhost:8080/api/weather"

    async def get_weather(self, lat: float, lon: float):
        async with httpx.AsyncClient(timeout=60.0) as client:
            params = {
                "lat": lat,
                "lon": lon
            }
            response = await client.get(self.base_url, params=params)
            return response.json()
    
class UserAPITester:
    def __init__(self):
        self.base_url = "http://localhost:8080/api/user"

    async def post_user(self):
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{self.base_url}/init")
            return response.json()

class PrewalkAPITester:
    def __init__(self):
        self.base_url = "http://localhost:8080/api/prewalk"

    async def post_init(self, user_uuid: str, lat: float, lon: float):
        async with httpx.AsyncClient(timeout=60.0) as client:
            params = {
                "user_uuid": user_uuid,
                "lat": lat,
                "lon": lon
            }
            response = await client.post(f"{self.base_url}/init", json=params)
            return response.json()
        
    async def post_intent(self, thread_id: str, user_prompt: str):
        async with httpx.AsyncClient(timeout=60.0) as client:
            params = {
                "thread_id": thread_id,
                "user_prompt": user_prompt
            }
            response = await client.post(f"{self.base_url}/intent", json=params)
            return response.json()
        
    async def get_weights(self, thread_id: str):
        async with httpx.AsyncClient(timeout=60.0) as client:
            params = {
                "thread_id": thread_id
            }
            response = await client.get(f"{self.base_url}/weights", params=params)
            return response.json()