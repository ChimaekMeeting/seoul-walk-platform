import folium

from frontend.streamlit_prototype.components.layer.map_layer import MapLayer


class NatureLayer:

    def __init__(self):
        self.map_layer = MapLayer()

    def add_to_map(
        self,
        m: folium.Map,
        center_lat: float,
        center_lon: float,
        route_nodes: list,
        G,
    ):
        """
        경로 노드 마커, 도보 네트워크 선, CCTV 마커를 Folium 지도에 오버레이합니다.
        """
        for node_id in route_nodes:
            if node_id in G.nodes:
                folium.CircleMarker(
                    location=[G.nodes[node_id]["y"], G.nodes[node_id]["x"]],
                    radius=3,
                    color="red",
                    fill=True,
                    fill_color="red",
                    fill_opacity=0.8,
                    tooltip=str(node_id),
                ).add_to(m)

        df_lines = self.map_layer.fetch_local_db_lines_optimized(center_lat, center_lon, radius_m=300)
        if not df_lines.empty:
            for _, row in df_lines.iterrows():
                flipped = [[c[1], c[0]] for c in row["path"]]
                folium.PolyLine(locations=flipped, color="#00BFFF", weight=2, opacity=0.4).add_to(m)

        df_cctv = self.map_layer.fetch_local_db_points(
            center_lat, center_lon, "safety_layer", "safety_type", "cctv", radius_m=1000
        )
        if not df_cctv.empty:
            for _, row in df_cctv.iterrows():
                folium.CircleMarker(
                    location=[row["lat"], row["lon"]],
                    radius=3,
                    color="#FFD700",
                    fill=True,
                    fill_color="#FFD700",
                    fill_opacity=0.7,
                    tooltip="CCTV",
                ).add_to(m)
