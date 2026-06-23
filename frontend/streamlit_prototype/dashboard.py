"""
서울시 보행 네트워크 대시보드

탭 1 – 개별 데이터 현황: 레이어별 포인트를 격자로 집계해 원 크기로 개수 표시
탭 2 – Walk Edge 점수: walk_edges 테이블의 각 점수를 선 색상으로 표시
"""

import json
import os

import folium
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from streamlit_folium import st_folium

import config.path_setup  # noqa: F401 — must precede all src/ imports (sys.path 부트스트랩)
from src.service.route.map_service import MapService

load_dotenv(encoding="utf-8")

SEOUL_CENTER = [37.5665, 126.9780]
SEOUL_ZOOM = 11
SEOUL_RADIUS_M = 30_000  # 서울 전역을 덮는 반경
POINT_LIMIT = 10_000  # 브라우저 성능 한계로 최대 렌더 개수 제한

PALETTE = [
    "#e74c3c", "#3498db", "#27ae60", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#16a085", "#8e44ad", "#c0392b",
    "#d35400", "#7f8c8d", "#2c3e50", "#f1c40f", "#2980b9",
]

# ── 레이어 설정 ───────────────────────────────────────────────────────────────
# 포인트 조회는 MapService에 위임 (테이블명/centroid/카테고리 컬럼은 서버가 캡슐화)
_map_service = MapService(kakao_client=None)

LAYER_OPTIONS: dict[str, tuple] = {
    "safety":   ("안전 (CCTV / 가로등)", _map_service.fetch_safety_points),
    "child":    ("어린이",              _map_service.fetch_child_points),
    "landmark": ("랜드마크",            _map_service.fetch_landmark_points),
    "nature":   ("자연 / 녹지",         _map_service.fetch_nature_points),
    "running":  ("러닝 코스",           _map_service.fetch_running_points),
}

SCORE_OPTIONS: dict[str, str] = {
    "safety_score": "안전 점수",
    "nature_score": "자연 점수",
    "slope_score": "경사 점수",
    "running_score": "러닝 점수",
    "landmark_score": "랜드마크 점수",
    "child_score": "어린이 점수",
}


# ── DB 연결 ───────────────────────────────────────────────────────────────────
@st.cache_resource
def _get_engine():
    url = (
        f"postgresql+psycopg2://{os.getenv('POSTGRES_USER')}:"
        f"{os.getenv('POSTGRES_PASSWORD')}@"
        f"{os.getenv('POSTGRES_HOST')}:"
        f"{os.getenv('POSTGRES_PORT')}/"
        f"{os.getenv('POSTGRES_DB')}"
    )
    return create_engine(url, pool_pre_ping=True)


# ── 데이터 로드 ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner="데이터 로딩 중…")
def load_layer_points(layer: str) -> pd.DataFrame:
    """MapService로 서울 전역 레이어 포인트를 가져옵니다. 최대 POINT_LIMIT개로 제한합니다."""
    df = LAYER_OPTIONS[layer][1](SEOUL_CENTER[0], SEOUL_CENTER[1], radius_m=SEOUL_RADIUS_M)
    if df.empty:
        return df
    df = df.head(POINT_LIMIT).rename(columns={"lon": "lng"})
    df["category"] = df["category"].fillna("기타") if "category" in df.columns else "기타"
    return df


@st.cache_data(ttl=300, show_spinner="엣지 데이터 로딩 중…")
def load_edge_scores(score_col: str, sample_rate: int) -> pd.DataFrame:
    """walk_edges에서 선택 점수와 geometry를 샘플링해 가져옵니다."""
    sql = f"""
        SELECT
            link_id,
            {score_col},
            ST_AsGeoJSON(geom) AS geom_json
        FROM walk_edges
        WHERE geom IS NOT NULL
          AND MOD(link_id, {sample_rate}) = 0
    """
    with _get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn)


# ── 유틸 ──────────────────────────────────────────────────────────────────────
def score_to_color(score: float, min_s: float, max_s: float) -> str:
    """점수 값을 빨강→초록 그라데이션 색상으로 변환합니다."""
    if max_s == min_s:
        return "#808080"
    t = max(0.0, min(1.0, (score - min_s) / (max_s - min_s)))
    r = int(255 * (1 - t))
    g = int(255 * t)
    return f"#{r:02x}{g:02x}00"


def build_color_map(categories: pd.Series) -> dict[str, str]:
    """카테고리 값마다 고유 색상을 할당합니다."""
    unique = sorted(str(c) for c in categories.dropna().unique())
    return {cat: PALETTE[i % len(PALETTE)] for i, cat in enumerate(unique)}


# ── 레이아웃 ──────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="서울시 보행 네트워크 대시보드",
    layout="wide",
    page_icon="🗺️",
)
st.title("🗺️ 서울시 보행 네트워크 대시보드")

tab1, tab2 = st.tabs(["📍 개별 데이터 현황", "🛣️ Walk Edge 점수"])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 – 레이어 개수 지도
# ═══════════════════════════════════════════════════════════════════════════════
with tab1:
    ctrl_col, map_col = st.columns([1, 3])

    with ctrl_col:
        st.subheader("설정")
        selected_layer = st.selectbox(
            "데이터 레이어",
            options=list(LAYER_OPTIONS.keys()),
            format_func=lambda k: LAYER_OPTIONS[k][0],
        )

        dot_radius = st.slider("점 크기", 2, 8, 4)
        dot_opacity = st.slider("투명도", 0.3, 1.0, 0.75, step=0.05)

        st.divider()

        df_layer = None
        try:
            df_layer = load_layer_points(selected_layer)
            total = len(df_layer)
            st.metric("표시 데이터 수", f"{total:,}개")
            if total >= POINT_LIMIT:
                st.warning(f"데이터가 많아 {POINT_LIMIT:,}개까지만 표시합니다.")

            color_map = build_color_map(df_layer["category"])

            st.subheader("카테고리 범례")
            cat_counts = df_layer["category"].value_counts()
            for cat, color in color_map.items():
                cnt = int(cat_counts.get(cat, 0))
                st.markdown(
                    f"<span style='display:inline-block;width:12px;height:12px;"
                    f"background:{color};border-radius:50%;margin-right:6px'></span>"
                    f"**{cat}** — {cnt:,}개",
                    unsafe_allow_html=True,
                )

        except Exception as exc:
            st.error(f"데이터 로드 실패: {exc}")

    with map_col:
        if df_layer is not None and not df_layer.empty:
            m = folium.Map(location=SEOUL_CENTER, zoom_start=SEOUL_ZOOM, tiles="CartoDB positron")
            color_map = build_color_map(df_layer["category"])

            # 카테고리별 FeatureGroup + GeoJSON으로 렌더링
            groups: dict[str, folium.FeatureGroup] = {
                cat: folium.FeatureGroup(name=cat, show=True)
                for cat in color_map
            }

            # GeoJSON FeatureCollection을 카테고리별로 분류
            cat_features: dict[str, list] = {cat: [] for cat in color_map}
            for _, row in df_layer.iterrows():
                cat = str(row["category"])
                if pd.isna(row["lat"]) or pd.isna(row["lng"]):
                    continue
                cat_features[cat].append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(row["lng"]), float(row["lat"])],
                    },
                    "properties": {"category": cat},
                })

            for cat, features in cat_features.items():
                if not features:
                    continue
                color = color_map[cat]
                folium.GeoJson(
                    {"type": "FeatureCollection", "features": features},
                    marker=folium.CircleMarker(
                        radius=dot_radius,
                        color=color,
                        fill=True,
                        fill_color=color,
                        fill_opacity=dot_opacity,
                        weight=0,
                    ),
                    tooltip=folium.GeoJsonTooltip(
                        fields=["category"], aliases=["유형"], localize=True
                    ),
                ).add_to(groups[cat])

            for fg in groups.values():
                fg.add_to(m)

            folium.LayerControl(collapsed=False).add_to(m)
            st_folium(m, width=None, height=620, returned_objects=[], use_container_width=True)
        else:
            st.info("표시할 데이터가 없습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 – Walk Edge 점수 지도
# ═══════════════════════════════════════════════════════════════════════════════
with tab2:
    ctrl_col2, map_col2 = st.columns([1, 3])

    df_edge = None  # map_col2 진입 전 반드시 초기화

    with ctrl_col2:
        st.subheader("설정")
        selected_score = st.selectbox(
            "시각화할 점수",
            options=list(SCORE_OPTIONS.keys()),
            format_func=lambda k: SCORE_OPTIONS[k],
        )

        sample_rate = st.select_slider(
            "샘플링 비율",
            options=[1, 2, 5, 10, 20, 50],
            value=10,
            format_func=lambda v: f"1/{v}" if v > 1 else "전체",
        )

        _edge_weight = st.slider("선 굵기", 1, 5, 2)

        st.divider()
        st.markdown("**색상 범례**")
        st.markdown(
            "<div style='display:flex;gap:4px;align-items:center'>"
            "<span style='background:linear-gradient(to right,#ff0000,#ffff00,#00ff00);"
            "width:120px;height:14px;border-radius:3px;display:inline-block'></span>"
            "<span style='font-size:12px'>낮음 → 높음</span></div>",
            unsafe_allow_html=True,
        )

        try:
            df_edge = load_edge_scores(selected_score, sample_rate)
            st.divider()
            st.metric("표시 엣지 수", f"{len(df_edge):,}개")
            if not df_edge.empty:
                col_a, col_b = st.columns(2)
                col_a.metric("최솟값", f"{df_edge[selected_score].min():.4f}")
                col_b.metric("최댓값", f"{df_edge[selected_score].max():.4f}")
                st.metric("평균값", f"{df_edge[selected_score].mean():.4f}")
        except Exception as exc:
            st.error(f"데이터 로드 실패: {exc}")

    with map_col2:
        if df_edge is not None and not df_edge.empty:
            m2 = folium.Map(location=SEOUL_CENTER, zoom_start=SEOUL_ZOOM, tiles="CartoDB positron")

            min_s = float(df_edge[selected_score].min())
            max_s = float(df_edge[selected_score].max())
            ew = int(_edge_weight)  # lambda 클로저 캡처용 로컬 복사

            features = []
            for _, row in df_edge.iterrows():
                raw = row["geom_json"]
                # SQLAlchemy가 JSON을 이미 dict로 변환했을 수 있으므로 두 경우 처리
                if isinstance(raw, dict):
                    geom = raw
                elif isinstance(raw, str):
                    geom = json.loads(raw)
                else:
                    continue
                score_val = row[selected_score]
                if pd.isna(score_val):
                    continue
                features.append({
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {
                        "color": score_to_color(float(score_val), min_s, max_s),
                        "score": round(float(score_val), 4),
                        "score_label": SCORE_OPTIONS[selected_score],
                    },
                })

            if features:
                folium.GeoJson(
                    {"type": "FeatureCollection", "features": features},
                    style_function=lambda f, _ew=ew: {
                        "color": f["properties"]["color"],
                        "weight": _ew,
                        "opacity": 0.75,
                    },
                    tooltip=folium.GeoJsonTooltip(
                        fields=["score_label", "score"],
                        aliases=["점수 종류", "값"],
                    ),
                ).add_to(m2)
                st_folium(m2, width=None, height=620, returned_objects=[], use_container_width=True)
            else:
                st.warning("렌더링할 엣지 데이터가 없습니다. 샘플링 비율을 낮춰보세요.")
        else:
            st.info("표시할 데이터가 없습니다.")
