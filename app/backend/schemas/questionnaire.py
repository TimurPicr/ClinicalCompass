from pydantic import BaseModel, Field, StrictInt, field_validator


class Question(BaseModel):
    id: int
    text: str
    options: list[str]


class Questionnaire(BaseModel):
    id: str
    title: str
    questions: list[Question]


class QuestionnaireSubmission(BaseModel):
    answers: list[StrictInt] = Field(
        min_length=5,
        max_length=5,
    )

    @field_validator("answers")
    @classmethod
    def validate_answers(cls, answers):
        for answer in answers:
            if answer < 0 or answer > 3:
                raise ValueError(
                    "Ответ должен находиться в диапазоне 0–3"
                )

        return answers


class QuestionnaireResult(BaseModel):
    score: int
    max_score: int
    note: str