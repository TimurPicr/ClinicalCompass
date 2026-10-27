def test_sleep_recommendation(doctor_client):
    client = doctor_client
    response = client.post(
        "/api/recommendations/preview",
        json={
            "answers": [0, 0, 3, 0, 0],
            "urgent_help_requested": False,
        },
    )

    assert response.status_code == 200

    data = response.json()

    codes = [
        item["code"]
        for item in data["recommendations"]
    ]

    assert "sleep_discussion" in codes


def test_no_recommendations(doctor_client):
    client = doctor_client
    response = client.post(
        "/api/recommendations/preview",
        json={
            "answers": [0, 0, 0, 0, 0],
            "urgent_help_requested": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["recommendations"] == []


def test_urgent_request(doctor_client):
    client = doctor_client
    response = client.post(
        "/api/recommendations/preview",
        json={
            "answers": [0, 0, 0, 0, 0],
            "urgent_help_requested": True,
        },
    )

    data = response.json()

    assert any(
        item["category"] == "mandatory"
        for item in data["recommendations"]
    )


def test_invalid_answers(doctor_client):
    client = doctor_client
    response = client.post(
        "/api/recommendations/preview",
        json={
            "answers": [0, 0, 10, 0, 0],
        },
    )

    assert response.status_code == 422
