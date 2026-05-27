# Cache Layer

**목적:** 짧은 TTL의 임시 데이터(현재 요청 중 주변 POI, 날씨/미세먼지 캐시, 채팅 세션 임시 상태 등) 저장을 담당합니다.

**유의사항:**
- 이 곳은 임시 저장 공간이며, 영구 보존용 저장소(DB)가 아닙니다.
- 실시간 POI, 날씨, 미세먼지처럼 자주 바뀌는 Layer 1.5 데이터에 짧은 TTL을 적용할 수 있습니다.
- cache miss 시에는 application이 external client 호출과 context 표준화 흐름을 다시 수행합니다.
