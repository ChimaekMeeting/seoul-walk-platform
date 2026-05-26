"""
base_network.py를 수정하지 않고 안전하게 walk_edges + walk_nodes를 적재하는 스크립트.
중복 link_id/node_id 제거 + 외래키 제약 우회 포함.

실행: python -m src.data.collectors.load_network_safe
"""

import pandas as pd
from sqlalchemy import text
from src.database.postgresql import engine


def load_network_safe():
    CSV_FILE_PATH = "src/data/raw/서울시 자치구별 도보 네트워크 공간정보.csv"

    print("📂 CSV 로딩 중...")
    try:
        df = pd.read_csv(CSV_FILE_PATH, encoding="cp949")
    except UnicodeDecodeError:
        df = pd.read_csv(CSV_FILE_PATH, encoding="utf-8")

    print(f"  전체 행 수: {len(df):,}")
    print(f"  컬럼 목록: {list(df.columns)}")

    # ──────────────────────────────────────────
    # 1. 노드 적재
    # ──────────────────────────────────────────
    nodes_df = df[df["노드링크 유형"] == "NODE"].copy()
    print(f"\n📍 NODE 행: {len(nodes_df):,}개")

    if len(nodes_df) == 0:
        print("  ⚠️  NODE 데이터 없음 — 컬럼명 확인 필요")
    else:
        # 컬럼명 후보 자동 감지
        node_id_col = next((c for c in df.columns if "노드" in c and "ID" in c), None)
        node_wkt_col = next((c for c in df.columns if "노드" in c and "WKT" in c), None)

        print(f"  node_id 컬럼: {node_id_col}")
        print(f"  node_wkt 컬럼: {node_wkt_col}")

        if not node_id_col or not node_wkt_col:
            print("  ❌ 노드 컬럼을 찾지 못했습니다. 아래 컬럼을 확인하세요:")
            print(f"     {list(df.columns)}")
            return

        nodes_df["geom"] = nodes_df[node_wkt_col].apply(lambda x: f"SRID=4326;{x}")
        processed_nodes = nodes_df[[node_id_col, "geom"]].rename(
            columns={node_id_col: "node_id"}
        )

        before = len(processed_nodes)
        processed_nodes = processed_nodes.drop_duplicates(subset=["node_id"])
        print(
            f"  중복 제거: {before - len(processed_nodes)}개 → {len(processed_nodes):,}개 남음"
        )

        with engine.begin() as conn:
            conn.execute(text("SET session_replication_role = replica;"))
            conn.execute(text("TRUNCATE TABLE walk_nodes RESTART IDENTITY CASCADE;"))
            processed_nodes.to_sql(
                "walk_nodes",
                con=conn,
                if_exists="append",
                index=False,
                method="multi",
                chunksize=10000,
            )
        print(f"  ✅ walk_nodes {len(processed_nodes):,}개 적재 완료")

    # ──────────────────────────────────────────
    # 2. 엣지 적재
    # ──────────────────────────────────────────
    edges_df = df[df["노드링크 유형"] == "LINK"].copy()
    print(f"\n🔗 LINK 행: {len(edges_df):,}개")

    edges_df["geom"] = edges_df["링크 WKT"].apply(lambda x: f"SRID=4326;{x}")
    processed_edges = edges_df[
        ["링크 ID", "시작노드 ID", "종료노드 ID", "링크 길이", "링크 유형 코드", "geom"]
    ].rename(
        columns={
            "링크 ID": "link_id",
            "시작노드 ID": "start_node",
            "종료노드 ID": "end_node",
            "링크 길이": "length_m",
            "링크 유형 코드": "road_type",
        }
    )

    before = len(processed_edges)
    processed_edges = processed_edges.drop_duplicates(subset=["link_id"])
    print(
        f"  중복 제거: {before - len(processed_edges)}개 → {len(processed_edges):,}개 남음"
    )

    with engine.begin() as conn:
        conn.execute(text("SET session_replication_role = replica;"))
        conn.execute(text("TRUNCATE TABLE walk_edges RESTART IDENTITY CASCADE;"))
        processed_edges.to_sql(
            "walk_edges",
            con=conn,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=10000,
        )
    print(f"  ✅ walk_edges {len(processed_edges):,}개 적재 완료")

    print("\n🎉 네트워크 적재 완료!")


if __name__ == "__main__":
    load_network_safe()
