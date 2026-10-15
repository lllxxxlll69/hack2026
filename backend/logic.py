"""Grounded answers: models select evidence; application formats claims from it."""
import re
import math
from collections import Counter
from datetime import datetime

MISSING = 'не найдено'
LABELS = {
    'student_name': 'ФИО студента', 'university': 'Название вуза',
    'program': 'Направление подготовки', 'study_form': 'Форма обучения',
    'study_start': 'Начало периода обучения', 'study_end': 'Окончание периода обучения',
    'document_number': 'Номер справки', 'issue_date': 'Дата выдачи',
    'signature_present': 'Подпись', 'seal_present': 'Печать',
    'group': 'Учебная группа', 'course': 'Курс', 'leave_reason': 'Причина отпуска',
    'leave_start': 'Дата начала отпуска', 'leave_end': 'Дата окончания отпуска',
    'application_date': 'Дата заявления', 'organization': 'Название организации',
    'internship_start': 'Дата начала практики', 'internship_end': 'Дата окончания практики',
    'supervisor_name': 'ФИО руководителя практики', 'grade': 'Оценка',
}
TYPE_FIELDS = {
    'study_certificate': ('Справка об обучении', 3, [
        'student_name', 'university', 'program', 'study_form', 'study_start', 'study_end',
        'document_number', 'issue_date', 'signature_present', 'seal_present']),
    'academic_leave_application': ('Заявление на академический отпуск', 4, [
        'student_name', 'group', 'course', 'leave_reason', 'leave_start', 'leave_end',
        'application_date', 'signature_present']),
    'internship_certificate': ('Справка о практике', 5, [
        'student_name', 'organization', 'internship_start', 'internship_end',
        'supervisor_name', 'grade', 'document_number', 'issue_date',
        'signature_present', 'seal_present']),
}


def built_in_types():
    result = {}
    for key, (title, section, fields) in TYPE_FIELDS.items():
        result[key] = {'title': title, 'fields': [
            {'key': f, 'label': LABELS[f], 'kind': 'boolean' if f.endswith('_present') else 'string',
             'required': True, 'rule': f'{section}.{2 if f == "signature_present" else 3 if f == "seal_present" else 1}'}
            for f in fields]}
    return result


def normalize_date(value):
    value = str(value).strip()
    for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля',
              'августа', 'сентября', 'октября', 'ноября', 'декабря']
    match = re.search(r'(\d{1,2})\s+(' + '|'.join(months) + r')\s+(\d{4})', value.lower())
    if match:
        try:
            return datetime(int(match[3]), months.index(match[2]) + 1, int(match[1])).date().isoformat()
        except ValueError:
            pass
    return MISSING


def normalize_fields(raw, config):
    result = {}
    for spec in config['fields']:
        key, value = spec['key'], raw.get(spec['key'])
        if spec['kind'] == 'boolean':
            result[key] = value is True  # 'false' as a string must never become True.
        else:
            value = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ''
            if not value or value.lower() in {'null', 'none', 'нет', 'отсутствует', 'не найдено'} or re.fullmatch(r'[_\s.\-]+', value):
                value = MISSING
            if (key.endswith(('_start', '_end', '_date')) or spec.get('format') == 'date') and value != MISSING:
                value = normalize_date(value)
            if key == 'course' and value != MISSING:
                match = re.search(r'\d+', value)
                value = match[0] if match else MISSING
            result[key] = value
    return result


def validate_fields(fields, config):
    required = [f for f in config['fields'] if f.get('required', True)]
    missing = [f['key'] for f in required if fields.get(f['key'], MISSING) in (MISSING, False, '', None)]
    applicable = [f for f in required if not missing or f['key'] in missing]
    return {'status': 'missing_fields' if missing else 'document_ok',
            'missing_fields': missing, 'sources': sorted({f"rule:{f['rule']}" for f in applicable})}


def parse_rules(text):
    rules = {}
    for line in text.splitlines():
        match = re.match(r'^\s*(\d+\.\d+)\.\s+(.+)', line)
        if match:
            if match[1] in rules:
                raise ValueError(f'Повторяющийся пункт {match[1]}')
            rules[match[1]] = match[2].strip()
    return rules


def unknown_answer():
    return {'answerable': False, 'value': None, 'sources': [],
            'answer': 'В документе и в Положении нет информации для ответа на этот вопрос. Обратитесь в деканат.'}


def with_quotes(result, fields, rules, config):
    labels = {f['key']: f['label'] for f in config['fields']} if config else LABELS
    result['quotes'] = []
    for source in result['sources']:
        kind, key = source.split(':', 1)
        if kind == 'rule' and key in rules:
            result['quotes'].append({'source': source, 'quote': rules[key]})
        elif kind == 'field' and key in fields:
            result['quotes'].append({'source': source, 'quote': f'{labels.get(key, key)}: {fields[key]}'})
    return result


def deterministic_answer(question, fields, config, rules):
    q = question.lower().replace('ё', 'е')
    if 'окончательн' in q and any(word in q for word in ('решение', 'принимает')) and '1.3' in rules:
        return {'answerable': True, 'value': 'сотрудник деканата', 'sources': ['rule:1.3'],
                'answer': 'Окончательное решение принимает сотрудник деканата, пункт 1.3 Положения.'}
    if config and any(term in q for term in ('все обязательн', 'комплектност', 'проверь документ', 'документ в порядке', 'чего не хватает', 'проверить документ')):
        result = validate_fields(fields, config)
        labels = {f['key']: f['label'] for f in config['fields']}
        refs = ', '.join(s.split(':')[1] for s in result['sources'])
        if result['missing_fields']:
            answer = 'Не хватает: ' + ', '.join(labels[k] for k in result['missing_fields']) + f'. Основание: пункты {refs} Положения.'
        else:
            answer = f'Документ содержит все обязательные сведения по пунктам {refs} Положения.'
        return {'answerable': True, 'value': result['status'], 'sources': result['sources'],
                'answer': answer + ' Окончательное решение примет сотрудник деканата.'}
    if config:
        # An exact requested field is answered without model interpretation.
        for spec in sorted(config['fields'], key=lambda f: len(f['label']), reverse=True):
            if spec['label'].lower().replace('ё', 'е') in q:
                return field_answer(spec['key'], fields, config)
    # If a requested topic is wholly absent from the knowledge base, no model call
    # can supply evidence. Newly added rules can make the same topic answerable.
    absent_topics = {
        'стоим': ('стоим', 'цена', 'оплат'), 'стипенд': ('стипенд',),
        'телефон': ('телефон',), 'кабинет': ('кабинет',),
        'срок рассмотр': ('срок рассмотр',),
    }
    source_text = ' '.join(rules.values()).lower()
    for query_token, evidence_tokens in absent_topics.items():
        if query_token in q and not any(token in source_text for token in evidence_tokens):
            return unknown_answer()
    return None


def field_answer(key, fields, config):
    if key not in fields or fields[key] in (MISSING, None, ''):
        return unknown_answer()
    label = next((f['label'] for f in config['fields'] if f['key'] == key), key)
    value = fields[key]
    value = ('есть' if value else 'нет') if isinstance(value, bool) else str(value)
    return {'answerable': True, 'value': value, 'sources': [f'field:{key}'], 'answer': f'{label}: {value}.'}


def requests_handoff(question):
    q = question.lower()
    return bool(re.search(r'(переведи|переключи|соедини|позови|свяжи|хочу|нужен|передай).*(деканат|сотрудник|человек|оператор)', q))


def retrieve_rules(question, rules, limit=8):
    """Local lexical retrieval with Russian prefix normalization; no remote embeddings."""
    stop = {'какой', 'какие', 'какова', 'докум', 'полож', 'студе', 'вопро', 'значе', 'поле', 'скажи', 'укажи', 'нужно'}

    def tokens(text):
        return [word[:5] for word in re.findall(r'[а-яёa-z]+', text.lower().replace('ё', 'е'))
                if len(word) > 3 and word[:5] not in stop]
    query = tokens(question)
    corpus = {key:Counter(tokens(value)) for key, value in rules.items()}
    if not corpus or not query:
        return {}
    count = len(corpus)
    frequencies = Counter(token for row in corpus.values() for token in row)
    scored = []
    for key, words in corpus.items():
        score = sum(math.log(1 + (count - frequencies[token] + .5) / (frequencies[token] + .5))
                    * words[token] / (words[token] + 1.5) for token in query if words[token])
        if score:
            scored.append((score, key))
    scored.sort(reverse=True)
    return {key:rules[key] for _, key in scored[:limit]}
