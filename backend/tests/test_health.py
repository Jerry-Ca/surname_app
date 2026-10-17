"""健康检查测试（契约第 3 节）：这是部署脚本依赖的接口，必须先测。"""

from __future__ import annotations


def test_health_returns_report(client) -> None:
    response = client.get("/api/health")
    assert response.status_code in (200, 503), response.text

    body = response.json()
    assert set(body) >= {
        "status", "api_version", "git_sha", "database", "model", "degraded", "checked_at",
    }
    assert body["status"] in {"ok", "degraded", "down"}
    assert set(body["database"]) >= {"connected", "dialect", "migration_revision"}
    assert set(body["model"]) >= {"configured", "provider", "model", "embedding_configured"}


def test_health_reports_degraded_without_model_keys(client) -> None:
    body = client.get("/api/health").json()
    assert body["model"]["configured"] is False
    assert "model_unavailable" in body["degraded"]
    # 数据库可用（内存 SQLite），因此不应是 down
    assert body["database"]["connected"] is True
    assert body["status"] == "degraded"


def test_root_endpoint_points_to_docs(client) -> None:
    body = client.get("/").json()
    assert body["service"] == "surname_app"
    assert body["docs"] == "/docs"
