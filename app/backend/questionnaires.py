"""Immutable clinical scales and validation for the four custom question types.

Russian items are transcribed from the Ministry of Health appendices cited below.
Scoring follows the instrument authors' manual. These are screeners, not diagnoses.
"""
from copy import deepcopy
import math
from fastapi import HTTPException

MANUAL_URL = 'https://www.phqscreeners.com/images/sites/g/files/g10016261/f/201412/instructions.pdf'
PHQ_RU_URL = 'https://static-0.minzdrav.gov.ru/system/attachments/attaches/000/054/893/original/Клинические_рекомендации_Старческая_астения_2020.pdf'
GAD_RU_URL = 'https://static.edu.rosminzdrav.ru/fc0001/fdpo/decanat/NMO_MZ/TEOC/u2/ИОТ/Generalizovannoe_trevozhnoe_rasstroistvo_KR/Generalizovannoe_trevozhnoe_rasstroistvo.pdf'
PHQ_ITEMS = [
    'Вас мало интересовали дела или ничто не доставляло удовольствие',
    'Вы испытывали чувство подавленности, депрессии или безнадежности',
    'У вас были проблемы с засыпанием или со сном, или вы слишком много спали',
    'Вы чувствовали усталость или испытывали недостаток энергии',
    'Плохой аппетит или переедание',
    'Вы испытывали чувство неудовлетворенности собой. Или думали о том, что вы неудачник, или что подводите себя или свою семью',
    'Трудности с концентрацией внимания, например, когда читаете газету или смотрите телевизор',
    'Вы делаете все или говорите так медленно, что другие люди начинают это замечать. Или наоборот — вам не сидится на месте или вы так неутомимы, что делаете гораздо больше, чем обычно',
    'Вам приходят мысли, что лучше всего было бы умереть или вы пытались поранить себя каким-то образом',
]
GAD_ITEMS = [
    'Повышенная нервная возбудимость, беспокойство и раздражительность',
    'Неспособность справиться с волнением',
    'Чрезмерное беспокойство по разному поводу',
    'Неспособность расслабиться',
    'Крайняя степень беспокойства: «не могу найти себе место»',
    'Легко поддаюсь чувству беспокойства или раздражительности',
    'Опасение чего-то страшного',
]


def standard_schema(kind):
    items = PHQ_ITEMS if kind == 'phq9' else GAD_ITEMS
    options = ['Не беспокоили', 'Несколько дней', 'Более половины всех дней', 'Почти ежедневно'] if kind == 'phq9' else ['Никогда', 'Несколько дней', 'Более половины дней', 'Почти каждый день']
    return {
        'instructions': 'В течение последних двух недель, как часто вас беспокоили следующие проблемы?',
        'questions': [{'id': f'q{i}', 'label': label, 'type': 'single', 'required': True,
                       'options': [{'value': n, 'label': option} for n, option in enumerate(options)]}
                      for i, label in enumerate(items, 1)],
        'sources': [{'title': 'Оригинальное руководство PHQ/GAD: подсчёт и условия использования', 'url': MANUAL_URL},
                    {'title': 'Русские формулировки: приложение Г10, стр. 80–81' if kind == 'phq9' else 'Русские формулировки: приложение Г2, стр. 67–68',
                     'url': PHQ_RU_URL if kind == 'phq9' else GAD_RU_URL}],
        'notice': 'Скрининг не устанавливает диагноз. Пригодность шкалы для конкретного пациента определяет врач. Применимость ко всем F00–F99 не установлена.',
        'license': 'PHQ/GAD: public domain, руководство авторов, стр. 8. Русский текст: приложение к клиническим рекомендациям.',
    }


def validate_schema(schema):
    if not isinstance(schema, dict) or not isinstance(schema.get('questions'), list) or not 1 <= len(schema['questions']) <= 50:
        raise HTTPException(422, 'Опросник должен содержать от 1 до 50 вопросов')
    seen = set()
    for question in schema['questions']:
        if not isinstance(question, dict):
            raise HTTPException(422, 'Некорректный вопрос')
        key, kind = question.get('id'), question.get('type')
        if not isinstance(key, str) or not 1 <= len(key) <= 80 or key in seen:
            raise HTTPException(422, 'Идентификаторы вопросов должны быть уникальными')
        seen.add(key)
        if not isinstance(question.get('label'), str) or not 1 <= len(question['label'].strip()) <= 2000:
            raise HTTPException(422, 'Укажите текст вопроса')
        if kind not in {'single', 'multiple', 'number', 'text'}:
            raise HTTPException(422, 'Неизвестный тип вопроса')
        if kind in {'single', 'multiple'}:
            options = question.get('options', [])
            if not isinstance(options, list) or not 2 <= len(options) <= 30:
                raise HTTPException(422, 'Укажите от 2 до 30 вариантов ответа')
            values = []
            for option in options:
                if not isinstance(option, dict) or not isinstance(option.get('value'), (str, int)) or isinstance(option.get('value'), bool) or not option.get('label'):
                    raise HTTPException(422, 'У варианта должны быть значение и подпись')
                if option['value'] in values:
                    raise HTTPException(422, 'Значения вариантов должны быть уникальными')
                values.append(option['value'])
        if kind == 'number':
            lo, hi = question.get('min', 0), question.get('max', 10)
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lo, hi)) or lo >= hi:
                raise HTTPException(422, 'Неверные границы числовой шкалы')
    return deepcopy(schema)


def validate_answers(snapshot, answers):
    if not isinstance(answers, dict):
        raise HTTPException(422, 'Ответы должны быть объектом')
    questions = snapshot['schema']['questions']
    allowed = {q['id'] for q in questions}
    if set(answers) - allowed:
        raise HTTPException(422, 'Ответ содержит неизвестные вопросы')
    for q in questions:
        key, kind = q['id'], q['type']
        if key not in answers:
            if q.get('required', True):
                raise HTTPException(422, f'Заполните вопрос {key}')
            continue
        value = answers[key]
        options = [o['value'] for o in q.get('options', [])]
        invalid = False
        if kind == 'single':
            invalid = isinstance(value, bool) or value not in options
        elif kind == 'multiple':
            invalid = not isinstance(value, list) or len(value) > len(options) or any(isinstance(v, bool) or v not in options for v in value) or len({str(v) for v in value}) != len(value)
        elif kind == 'number':
            invalid = isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not q.get('min', 0) <= value <= q.get('max', 10)
        elif kind == 'text':
            invalid = not isinstance(value, str) or len(value) > 5000
        if invalid:
            raise HTTPException(422, f'Некорректный ответ на вопрос {key}')
    kind = snapshot.get('kind')
    if kind in {'phq9', 'gad7'}:
        count = 9 if kind == 'phq9' else 7
        if len(answers) != count or any(type(answers.get(f'q{i}')) is not int or not 0 <= answers[f'q{i}'] <= 3 for i in range(1, count + 1)):
            raise HTTPException(422, 'Для клинической шкалы требуются все целочисленные ответы 0–3')
        return sum(answers.values())
    return None


def severity_label(kind, score):
    if score is None:
        return None
    if kind == 'phq9':
        return next(label for threshold, label in [(20, 'Тяжёлая'), (15, 'Умеренно тяжёлая'), (10, 'Умеренная'), (5, 'Лёгкая'), (0, 'Минимальная')] if score >= threshold)
    if kind == 'gad7':
        return next(label for threshold, label in [(15, 'Тяжёлая'), (10, 'Умеренная'), (5, 'Лёгкая'), (0, 'Минимальная')] if score >= threshold)
    return None
