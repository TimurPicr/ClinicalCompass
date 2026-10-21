from fastapi.testclient import TestClient

from app.backend.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok"
    }


def test_get_questionnaire():
    response = client.get(
        "/api/questionnaires/demo"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == "demo"
    assert len(data["questions"]) == 5


def test_submit_questionnaire():
    response = client.post(
        "/api/questionnaires/demo/submit",
        json={
            "answers": [1, 2, 3, 1, 0]
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["score"] == 7
    assert data["max_score"] == 15


def test_invalid_answers():
    response = client.post(
        "/api/questionnaires/demo/submit",
        json={
            "answers": [1, 2, 10, 1, 0]
        },
    )

    assert response.status_code == 422