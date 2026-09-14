import json

from tools.integration_soak import run_soak


def test_integration_soak_exercises_repeated_document_lifecycles(tmp_path) -> None:
    output = tmp_path / "reports" / "integration-memory.json"

    report = run_soak(cycles=3, timeout=10.0, output=output)

    assert report["status"] == "passed"
    assert report["cycles"] == 3
    assert report["pages_rendered"] == 9
    assert report["rss_measurement_available"]
    assert report["leaked_temporary_workspaces"] == []
    assert report["steady_state_growth_bytes"] <= report[
        "steady_state_growth_limit_bytes"
    ]
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "passed"
