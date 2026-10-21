from app.backend.schemas.recommendation import (
    RecommendationItem,
)


def check_sleep_problems(
    answers: list[int],
) -> RecommendationItem | None:

    # В учебном опроснике вопрос №3 связан со сном.
    if answers[2] >= 2:
        return RecommendationItem(
            code="sleep_discussion",
            category="desirable",
            title="Обсуждение качества сна",
            description=(
                "Пациент часто сообщает о трудностях "
                "со сном. Предлагается обсудить "
                "эту жалобу на консультации."
            ),
            source="demo_rule_v1",
        )

    return None


def check_concentration_problems(
    answers: list[int],
) -> RecommendationItem | None:

    if answers[0] >= 2:
        return RecommendationItem(
            code="concentration_discussion",
            category="desirable",
            title="Обсуждение концентрации",
            description=(
                "Пациент сообщает о частых трудностях "
                "с концентрацией. Предлагается уточнить "
                "эту жалобу на консультации."
            ),
            source="demo_rule_v1",
        )

    return None


def check_urgent_request(
    urgent_help_requested: bool,
) -> RecommendationItem | None:

    if urgent_help_requested:
        return RecommendationItem(
            code="urgent_contact",
            category="mandatory",
            title="Запрос срочной помощи",
            description=(
                "Пациент указал, что ему необходима "
                "срочная помощь. При непосредственной "
                "угрозе жизни следует немедленно "
                "обратиться в экстренные службы. "
                "Этот запрос пока не отправляет "
                "уведомление врачу."
            ),
            source="demo_rule_v1",
        )

    return None