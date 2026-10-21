from app.backend.schemas.questionnaire import Questionnaire


DEMO_QUESTIONS = [
    {
        "id": 1,
        "text": "Как часто вам было трудно сосредоточиться?",
        "options": [
            "Никогда",
            "Редко",
            "Часто",
            "Почти всегда",
        ],
    },
    {
        "id": 2,
        "text": "Как часто вы испытывали беспокойство?",
        "options": [
            "Никогда",
            "Редко",
            "Часто",
            "Почти всегда",
        ],
    },
    {
        "id": 3,
        "text": "Как часто вам было трудно заснуть?",
        "options": [
            "Никогда",
            "Редко",
            "Часто",
            "Почти всегда",
        ],
    },
    {
        "id": 4,
        "text": "Как часто вы испытывали недостаток энергии?",
        "options": [
            "Никогда",
            "Редко",
            "Часто",
            "Почти всегда",
        ],
    },
    {
        "id": 5,
        "text": "Как часто вам было трудно выполнять обычные дела?",
        "options": [
            "Никогда",
            "Редко",
            "Часто",
            "Почти всегда",
        ],
    },
]


def get_demo_questionnaire() -> Questionnaire:
    return Questionnaire(
        id="demo",
        title="Учебный опросник самочувствия",
        questions=DEMO_QUESTIONS,
    )


def calculate_score(answers: list[int]) -> int:
    return sum(answers)