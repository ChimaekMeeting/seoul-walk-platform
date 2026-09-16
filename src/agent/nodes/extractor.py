import json, logging, re
from typing import Optional
from pydantic import BaseModel
from langchain_core.output_parsers import StrOutputParser
from src.schema.prewalk_schema import State, Location
from src.interfaces.schema.walk_schema import WalkMode
from src.infrastructure.external.client.gpt_client import GPTClient
from src.agent.utils.chatbot_utils import PromptUtils
from src.agent.tools.mode_tools import ModeTool
from src.repository.user.user_preference_repository import UserPreferenceRepository

logger = logging.getLogger(__name__)

# 근거: 대한민국 정책브리핑 "시속 4km, 인간의 속도"(2011, korea.kr)
_WALK_SPEED_KMH: float = 4.0

# extraction.yaml [3]에 넣은 대응표와 같은 소스(WalkMode) — Preference.mode 값과 tool 이름 대응.
_MODE_TO_TOOL = {
    "circular_random":  "select_circular",
    "oneway_random":    "select_oneway",
    "oneway_shortest":  "select_oneway_shortest",
    "gps_art":          "select_gps_art",
    "waypoint":         "select_waypoint",
}

# 예외6의 "새 필드가 생겼다"는 정당화는 이 필드들(어디로/어떤 모양으로 — 모드의 정체성을
# 바꾸는 필드)만 인정한다. target_km/target_minutes는 제외한다 — 최단(oneway_shortest)엔
# 원래 이 필드가 없어서, 단순히 거리 숫자를 언급하기만 해도 "새 필드가 생겼다"는 조건을
# 항상 만족해버려 case_105류(거리만 요구했는데 편도로 튐)를 못 잡기 때문이다.
_STRUCTURAL_FIELDS = {"destination", "waypoints", "shape", "legs"}

# 예외6에서 "새 필드가 안 생겨도" 전환을 인정하는 명시적 키워드. extraction.yaml [1-C]가
# 도구 선택 트리거로 쓰는 단어들과 맞춘다 — 새 규칙을 만드는 게 아니라 그 프롬프트 규칙이
# 실제로 지켜졌는지를 이 계층에서 재확인하는 것이다. 편도→최단(필드가 줄기만 함)이나
# 순환으로의 전환(필드 구성이 옛 모드와 같아짐)처럼 _STRUCTURAL_FIELDS만으로는 "새 필드"가
# 생기지 않는 전환이 있어서(case_114/115/116/117), 이 키워드 확인 없이는 항상 되돌려진다.
_MODE_CHANGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "select_oneway_shortest": ("최단", "최단경로", "빨리", "빠르게", "지름길", "곧장"),
    "select_oneway":          ("편도", "우회"),
    "select_circular":        ("순환", "한 바퀴", "동그랗게"),
    "select_waypoint":        ("거쳐", "들렀다가", "지나서"),
}

# ── user_prompt 정규화(LLM 호출 전 전처리) ──────────────────────────────────
# extraction.yaml에 "이런 노이즈는 무시하라"고 지시하는 대신, 결정론적 파이썬 로직으로
# 애초에 깨끗한 텍스트를 LLM에 넘긴다 — 재현 가능하고 프롬프트 길이도 안 늘어난다.
_HTML_TAG_RE = re.compile(r"<[^>]+>")
# 이 시스템은 톤(ㅋㅋㅋ, !!! 등)이 아니라 모드/장소/거리/테마 같은 정해진 정보만 뽑으면 되고,
# 정규화된 텍스트는 LLM 입력으로만 쓰일 뿐 사용자에게 다시 보여주지 않는다 — 반복 횟수 자체가
# 추출 결과에 영향을 줄 이유가 없으므로 단어·문자열 구분 없이 같은 기준(3회 이상 → 2회)을 쓴다.
# {2,}는 첫 캡처 이후 "추가로" 몇 번 더 반복되는지를 세는 것이라, 실제 총 등장 횟수는 +1이다.
_REPEATED_WORD_RE = re.compile(r"\b(\S{1,20})(?:\s+\1\b){2,}")  # 같은 단어가 공백으로 총 3회+ 반복
_REPEATED_CHUNK_RE = re.compile(r"(.{1,20}?)\1{2,}")  # 같은 문자열(문자 1개 포함)이 붙어서 총 3회+ 반복
_WHITESPACE_RUN_RE = re.compile(r"\s+")


def _sanitize_user_prompt(text: str) -> str:
    """
    HTML 태그·과도한 공백/줄바꿈·반복 문자열을 제거해 LLM에 넘길 발화를 정규화한다.
    의미는 판단하지 않고 결정론적 규칙만 적용하며, State.user_prompt 원본은 건드리지 않는다
    (Interviewer·ConfirmationClassifier·로그는 원문을 그대로 본다).
    """
    if not text:
        return text
    text = _HTML_TAG_RE.sub(" ", text)
    text = _REPEATED_WORD_RE.sub(lambda m: f"{m.group(1)} {m.group(1)}", text)
    text = _REPEATED_CHUNK_RE.sub(lambda m: m.group(1) * 2, text)
    text = _WHITESPACE_RUN_RE.sub(" ", text).strip()
    return text


def _is_null_placeholder(value: object) -> bool:
    """
    LLM이 진짜 null 대신 문자열 "null"을 그대로 채워 보내는 경우를 잡는다(예: origin="null",
    또는 {"place_name": "null", ...}). extraction.yaml [2]가 "빈 값은 문자열 'null'이 아니라
    실제 null로 두라"고 명시하는데도 가끔 이렇게 나온다 — 값 자체를 못 믿는 것이므로 예외3~10
    전체가 진짜 None을 보게 여기서 먼저 걸러낸다.
    """
    if isinstance(value, str):
        return value.strip().lower() == "null"
    if isinstance(value, dict):
        return str(value.get("place_name", "")).strip().lower() == "null"
    return False


class Extractor(GPTClient):
    def __init__(self):
        super().__init__()
        self.mode_tool    = ModeTool()
        self.model        = self.llm.bind_tools(self.mode_tool.tools)
        self.prompt_utils = PromptUtils()
        self.str_parser   = StrOutputParser()

    async def run(self, state: State) -> State:
        """
        모드/위치 추출(tool_call) 후 테마 태그를 추출해 State에 저장합니다.
        """
        # LLM 호출 전 정규화. State.user_prompt 자체는 바꾸지 않는다 — 예외5의 출발
        # 표현 검사나 Interviewer·ConfirmationClassifier·로그는 원문을 그대로 봐야 한다.
        sanitized_prompt = _sanitize_user_prompt(state.user_prompt)

        input_variables = {
            "user_input":             sanitized_prompt,
            "current_context":        self.prompt_utils.format_for_prompt(state.user_context),
        }

        # extractor 응답 생성
        try:
            res = await super().get_response(
                prompt_name     = "extraction",
                input_variables = input_variables,
                llm             = self.model,
            )
        except Exception:
            logger.exception("extractor_llm_error")
            return state

        # 예외1. 산책 모드를 결정하지 못한 경우
        if not res or not res.tool_calls:
            logger.warning("LLM이 산책 모드를 결정하지 못했습니다.")
            return state

        tool_call = res.tool_calls[0]
        tool_name = tool_call["name"]  # LLM이 결정한 산책 모드

        # 예외2. 정의되지 않은 산책 모드를 사용하는 경우
        if tool_name not in self.mode_tool.tool_map:
            logger.warning(f"LLM이 정의되지 않은 산책 모드를 사용합니다: {tool_name}")
            return state

        # LLM이 추출한 산책 모드 외 정보 — 예외3~10(결정론적 보정)은 별도 메서드로 분리해
        # eval_extraction.py 등에서 "이 tool_call이 후처리를 거치면 최종적으로 어떤 Preference가
        # 되는지"를 이 run()과 같은 LLM 호출을 새로 만들지 않고도 재현할 수 있게 한다.
        args = tool_call["args"]
        pref = self._apply_postprocessing(tool_name, args, state)
        if pref is None:
            return state

        state.mode         = pref.mode
        state.user_context = pref
        # GPS Art는 도형 모양대로만 경로를 잇고 GpsArtEngine이 custom_weights/profile을 쓰지 않아
        # themes.yaml 호출 결과가 어차피 반영되지 않으므로 불필요한 LLM 호출을 건너뛴다.
        state.themes       = [] if pref.mode == WalkMode.GPS_ART else await self._extract_themes(sanitized_prompt)

        # 로그
        logger.info(f"user_prompt: {state.user_prompt}")
        logger.info(f"mode: {state.mode}")
        logger.info(f"user_context: {state.user_context.model_dump_json() if state.user_context else None}")
        logger.info(f"themes: {state.themes}")

        return state

    def _apply_postprocessing(self, tool_name: str, args: dict, state: State):
        """
        예외3~10: LLM이 낸 tool_name/args에 결정론적 보정을 적용해 최종 Preference를 반환한다.
        tool invoke 자체가 실패하면(예외10) None을 반환한다. LLM을 새로 호출하지 않는
        순수 함수라 run()과 eval_extraction.py 양쪽에서 같은 tool_call 결과에 대해
        재현 가능하게 호출할 수 있다.
        """
        prior_context = state.user_context  # 이번 턴 추출 전 State(직전 place_name과 비교하기 위함)

        # 예외3. LLM이 필드값으로 진짜 null 대신 문자열 "null"을 채운 경우 실제 None으로
        #   정규화한다. 이후 예외4~10 전부가 이 정규화된 args를 보게 하기 위해 가장 먼저 실행한다
        #   (예: case_118류 — origin이 "null" 문자열로 와서 예외7의 "None이면 보존" 체크에
        #   안 걸리던 문제).
        for field_name, value in list(args.items()):
            if _is_null_placeholder(value):
                args[field_name] = None
                logger.info(f"{field_name}이 문자열 \"null\"로 와서 실제 None으로 정규화했습니다.")

        # 예외4. LLM이 place_name과 함께 스스로 채운 좌표를 검증한다.
        #   - 직전 place_name과 다르면(새로 언급된 장소) 좌표를 지워 Interviewer의 Kakao 재검증을 강제한다.
        #     실시간 검증이 안 된 값이라 서울 밖 좌표를 그대로 들고 확인 단계까지 갈 수 있다(is_within_seoul_bbox 우회).
        #   - 직전 place_name과 같으면(같은 장소 재언급) 새로 채운 좌표 대신 직전에 이미 확정된 좌표로 덮어써
        #     불필요한 재검색과 LLM의 이번 턴 헛채움을 함께 막는다.
        #   - 현재 위치와 정확히 일치하는 좌표("여기"/"현재 위치" 처리)는 그대로 신뢰한다.
        self._reconcile_location_arg(
            args.get("origin"),
            prior_context.origin if prior_context else None,
            state.current_location,
        )
        self._reconcile_location_arg(
            args.get("destination"),
            getattr(prior_context, "destination", None) if prior_context else None,
            state.current_location,
        )

        # 예외5. origin과 destination이 동일한 장소명인데 명시적 출발지 표현이 없는 경우
        # (e.g., "용산역으로 가는 길 알려줘" → origin을 null로 보정해 현재 위치로 대체)
        _EXPLICIT_ORIGIN_MARKERS = ("에서", "부터", "출발", "시작")
        origin_arg = args.get("origin")
        dest_arg   = args.get("destination")
        if origin_arg and dest_arg:
            # LLM이 dict 대신 장소명 문자열만 넘기는 경우도 있어 두 형태 모두 처리한다.
            origin_name = origin_arg.get("place_name") if isinstance(origin_arg, dict) else origin_arg if isinstance(origin_arg, str) else None
            dest_name   = dest_arg.get("place_name")   if isinstance(dest_arg,   dict) else dest_arg   if isinstance(dest_arg,   str) else None
            if origin_name and dest_name and origin_name == dest_name:
                if not any(m in state.user_prompt for m in _EXPLICIT_ORIGIN_MARKERS):
                    args["origin"] = None
                    logger.warning(
                        f"origin과 destination이 동일한 장소명({origin_name})이며 "
                        f"명시적 출발지 표현이 없어 origin을 null로 보정합니다."
                    )

        # 예외6. 모드가 바뀌었는데 그 전환을 정당화할 새 정보가 이번 발화에 없다면 옛
        #   도구로 되돌린다. extraction.yaml [3]는 "명시적으로 다르게 요구했을 때만 모드를
        #   바꾸라"고 하지만, 지침만으로는 목적지·거리 변경 요청만으로도 종종 select_oneway로
        #   튀는 현상이 남아있었다(case_105/108류 — 최단/편도 context에 이미 있던 destination을
        #   바꾸거나 거리를 요구했을 뿐인데 도구까지 바뀜). 두 조건 중 하나라도 있으면 전환을
        #   인정하고, 둘 다 없으면 되돌린다:
        #     (a) 새 도구가 요구하는 "정체성" 필드(_STRUCTURAL_FIELDS — 어디로/어떤 모양으로)
        #         중 옛 모드(Preference)엔 아예 없던 필드가 이번 args에 실제로 채워졌다
        #         (예: 순환→편도 전환에서 destination이 새로 생김). target_km/target_minutes는
        #         제외한다 — 최단엔 원래 이 필드가 없어서 거리만 언급해도 "새 필드가 생겼다"는
        #         조건을 항상 만족해버리면 case_105류(거리만 요구했는데 편도로 튐)를 못 잡는다.
        #     (b) 새 도구에 대응하는 명시적 전환 키워드(_MODE_CHANGE_KEYWORDS)가 원문에 있다
        #         (예: 편도→최단처럼 필드가 오히려 줄기만 하거나, 순환으로 바뀌면서 필드
        #         구성이 옛 모드와 같아지는 경우 — (a)만으로는 못 잡으므로 이 키워드 확인이
        #         필요하다. case_114/115/116/117류).
        #   되돌릴 때 옛 도구가 안 받는 필드(예: target_km→최단 전환 무산 시)는 같이 버린다.
        if prior_context is not None:
            prior_tool = _MODE_TO_TOOL.get(prior_context.mode.value)
            if prior_tool is not None and tool_name != prior_tool:
                prior_fields = set(prior_context.model_dump().keys()) - {"mode"}
                new_tool_fields = set(self.mode_tool.tool_map[tool_name].args.keys())
                genuinely_new_fields = (new_tool_fields - prior_fields) & _STRUCTURAL_FIELDS
                # is not None이 아니라 truthy로 본다 — waypoints/legs는 "언급 안 함"이 빈
                # 리스트([])로 올 수도 있는데, is not None으로는 그걸 "새로 채워졌다"고 오판한다.
                has_new_field_value = any(bool(args.get(f)) for f in genuinely_new_fields)
                has_explicit_keyword = any(
                    kw in state.user_prompt for kw in _MODE_CHANGE_KEYWORDS.get(tool_name, ())
                )
                if not has_new_field_value and not has_explicit_keyword:
                    logger.info(
                        f"{tool_name}로 바뀔 새 필드나 명시적 전환 표현이 없어 "
                        f"이전 도구({prior_tool})로 되돌립니다: args={args}"
                    )
                    tool_name = prior_tool
                    allowed_fields = self.mode_tool.tool_map[tool_name].args.keys()
                    args = {k: v for k, v in args.items() if k in allowed_fields}

        # 예외7. 모드 변경 여부와 무관하게, 이번 턴에 값이 없는(누락됐거나 null인) 필드를
        #   직전 context에서 그대로 보존한다. 지침(extraction.yaml [3])만으로는 모델이
        #   모드가 바뀔 때 origin/target_km 같은 공유 필드를 자꾸 놓쳐서(회귀 없이는 문구를
        #   더 강하게 쓸 수도 없어) 여기서 결정론적으로 보정한다.
        #   - 최종 도구가 실제로 받는 필드 이름 기준으로 순회한다(tool_map[tool_name].args) —
        #     LLM이 그 필드를 아예 안 넣고 생략한 경우(키 자체가 없는 경우)까지 잡기 위함이다.
        #   - 새 도구에 있어도 직전 context엔 그 필드 자체가 없었다면(예: 순환→편도 전환의
        #     destination) prior_value가 None이라 그대로 비워둔다 — 이건 진짜로 새로 물어봐야 한다.
        #   - 다음 예외(origin 없으면 현재 위치로 대체)보다 먼저 실행해, context에 origin이
        #     있으면 그쪽을 현재 GPS 위치보다 우선한다.
        if prior_context is not None:
            for field_name in self.mode_tool.tool_map[tool_name].args.keys():
                if args.get(field_name) is None:
                    prior_value = getattr(prior_context, field_name, None)
                    if prior_value is not None:
                        args[field_name] = (
                            prior_value.model_dump() if isinstance(prior_value, BaseModel) else prior_value
                        )
                        logger.info(f"{field_name} 미언급 → 직전 context 값으로 보존: {args[field_name]}")

        # 예외8. 출발지가 없는 경우
        if args.get("origin") is None:
            args["origin"] = state.current_location.model_dump()
            logger.warning(f"출발지가 정해지지 않아, 현 위치를 출발지로 설정합니다: {args['origin']}")

        # 예외9. target_km/target_minutes 정리(target_km 필드가 있는 도구에서만 —
        #   select_oneway_shortest·select_waypoint는 이 필드 자체가 없음).
        #   - target_minutes가 있으면(이번 턴에 시간으로 새 거리를 말했다는 뜻) 무조건 최우선으로
        #     _WALK_SPEED_KMH로 환산해 target_km을 덮어쓴다. target_km에 값이 있어도(부분 수정
        #     상황에서 [Current Context]의 옛 km이 그대로 실려 왔을 수 있음) 이번 턴의 시간
        #     언급이 그 값보다 우선한다 — extraction.yaml [3]의 예외 규칙과 짝을 맞춘 순서다.
        #   - target_minutes가 없고 target_km만 있으면 그대로 쓴다.
        #   - 둘 다 없으면 사용자가 온보딩에서 고른 기본 거리(UserPreference.default_target_km)를
        #     쓴다. 그마저 없으면(온보딩 미완료 또는 거리 미선택) target_km을 채우지 않고 비워둔다
        #     — 임의 기본값으로 조용히 채우지 않고, Interviewer의 기존 "target_km 없음 → 재질문"
        #     흐름(_is_complete/_get_missing_info)에 맡긴다.
        #   - 2026-09-14 버그 수정: 이전에는 `if "target_km" in args`로 게이팅했는데, LLM이
        #     시간만 언급된 첫 요청(예: "45분 편도로 걷고 싶어", [Current Context] 없음)에서는
        #     tool_call에 target_km 키 자체를 아예 안 넣는 경우가 있어(선택 필드라 생략)
        #     이 조건이 거짓이 되고, target_minutes가 통째로 버려져(select_circular/
        #     select_oneway/select_gps_art는 target_minutes를 받아도 쓰지 않고 버림) 거리가
        #     조용히 사라지는 문제가 있었다. 부분 수정 상황에서만 우연히 안 드러났던 이유는
        #     예외7(위)이 먼저 실행되며 [Current Context]의 옛 target_km 값을 args에 채워 넣어
        #     이 조건을 우연히 만족시켰기 때문이다(scripts/eval_extraction.py case_008 참고).
        #     이제 args에 실제로 그 키가 있는지가 아니라, 이 도구가 애초에 target_km 필드를
        #     받는지로 판단한다.
        if "target_km" in self.mode_tool.tool_map[tool_name].args:
            minutes = args.pop("target_minutes", None)
            if minutes is not None:
                args["target_km"] = minutes * _WALK_SPEED_KMH / 60
                logger.info(f"target_minutes={minutes}분을 target_km={args['target_km']:.3f}km로 환산했습니다.")
            elif args.get("target_km") is None:
                preference = UserPreferenceRepository.get_by_user_id(state.user_id)
                default_km = getattr(preference, "default_target_km", None) if preference else None
                if default_km is not None:
                    args["target_km"] = default_km
                    logger.info(f"거리·시간 언급이 없어 온보딩 선호 거리 target_km={default_km}km를 채웠습니다.")
                else:
                    logger.info("거리·시간 언급도 온보딩 선호 거리도 없어 target_km을 비워둡니다(Interviewer 재질문).")

        # 예외10. tool 호출 자체가 실패하는 경우(예: LLM이 예상 밖 형식의 인자를 채운 경우)
        try:
            return self.mode_tool.tool_map[tool_name].invoke(args)
        except Exception:
            logger.exception(f"산책 모드 도구 호출에 실패했습니다: tool_name={tool_name}, args={args}")
            return None

    @staticmethod
    def _reconcile_location_arg(
        loc_arg,
        prior_loc: Optional[Location],
        current_location: Location,
    ) -> None:
        """
        LLM이 tool 호출 인자에 채운 좌표를 검증한다.
        - 현재 위치와 정확히 일치하면 그대로 둔다("여기"/"현재 위치" 처리).
        - place_name이 직전 State 값과 같다면(같은 장소 재언급) 새로 채운(또는 빈) 좌표 대신
          직전에 이미 확정된 좌표로 덮어써 불필요한 재검색과 LLM의 헛채움을 함께 막는다.
        - place_name이 다르거나 비교할 직전 값이 없다면(새로 언급된 장소) 좌표를 지워
          place_name만 남기고 Interviewer의 Kakao 검색·bbox 검증을 강제한다.
        """
        if not isinstance(loc_arg, dict):
            return

        place_name = loc_arg.get("place_name")
        lat, lon   = loc_arg.get("lat"), loc_arg.get("lon")

        if (
            lat is not None and lon is not None
            and current_location.lat is not None and current_location.lon is not None
            and abs(lat - current_location.lat) < 1e-6
            and abs(lon - current_location.lon) < 1e-6
        ):
            return

        if (
            prior_loc is not None
            and prior_loc.place_name is not None
            and place_name == prior_loc.place_name
        ):
            loc_arg["lat"]     = prior_loc.lat
            loc_arg["lon"]     = prior_loc.lon
            loc_arg["address"] = prior_loc.address
            return

        loc_arg["lat"]     = None
        loc_arg["lon"]     = None
        loc_arg["address"] = None

    async def _extract_themes(self, user_input: str) -> list[str]:
        """
        발화에서 TAG_WEIGHT_MAP 키에 해당하는 테마 태그를 0~3개 추출합니다.
        LLM 응답 파싱 실패 시 빈 리스트를 반환합니다.
        """
        from src.service.user.survey_service import TAG_WEIGHT_MAP  # 순환 import 방지(지연 로드)

        tag_keys = list(TAG_WEIGHT_MAP.keys())
        try:
            res = await super().get_response(
                prompt_name     = "themes",
                input_variables = {"user_input": user_input, "tag_keys": tag_keys},
                parser          = self.str_parser,
            )
            tags = json.loads(res)
            return [t for t in tags if t in TAG_WEIGHT_MAP]
        except Exception:
            logger.warning("사용자 프롬프트에서 테마를 추출하지 못했습니다.")
            return []
