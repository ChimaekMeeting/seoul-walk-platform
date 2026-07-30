from src.interfaces import dependencies


def test_runtime_graph_uses_database_by_default(monkeypatch):
    expected = object()
    monkeypatch.setattr(dependencies.settings, "WALK_GRAPH_SOURCE", "database")
    monkeypatch.setattr(
        dependencies.GraphRepository,
        "load_graph",
        lambda: expected,
    )

    assert dependencies.load_runtime_graph() is expected


def test_runtime_graph_uses_artifact_in_deployment_mode(monkeypatch):
    expected = object()
    monkeypatch.setattr(dependencies.settings, "WALK_GRAPH_SOURCE", "artifact")
    monkeypatch.setattr(
        dependencies.settings,
        "WALK_GRAPH_ARTIFACT_PATH",
        "artifacts/test.pkl",
    )
    monkeypatch.setattr(
        dependencies.settings,
        "WALK_GRAPH_DATA_VERSION",
        "test-v1",
    )
    monkeypatch.setattr(
        dependencies.settings,
        "WALK_GRAPH_EXPECTED_COMMIT",
        "abc123",
    )
    monkeypatch.setattr(
        dependencies.GraphArtifactRepository,
        "load",
        lambda path, **kwargs: (expected, path, kwargs),
    )

    graph, path, options = dependencies.load_runtime_graph()

    assert graph is expected
    assert path == "artifacts/test.pkl"
    assert options == {
        "expected_data_version": "test-v1",
        "expected_source_commit": "abc123",
    }
