import pickle

with open("artifacts/walk_graph_v1.pkl", "rb") as f:
    G = pickle.load(f)

graph_ids = {d["link_id"] for _, _, d in G.edges(data=True) if "link_id" in d}
db_ids = {int(line) for line in open("/tmp/db_link_ids.txt") if line.strip()}

print(f"그래프 link_id : {len(graph_ids):,}")
print(f"DB link_id     : {len(db_ids):,}")

only_graph = graph_ids - db_ids
only_db = db_ids - graph_ids

print(f"\n그래프에만 있음 : {len(only_graph):,}")
print(f"DB에만 있음     : {len(only_db):,}")

if not only_graph:
    print("\n✅ 정합성 OK — 그래프의 모든 link_id가 DB에 존재")
else:
    print(f"\n❌ 불일치 — 예시 10개: {sorted(only_graph)[:10]}")