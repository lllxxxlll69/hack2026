"""Independent evidence reports and local clause search; no model-generated facts."""
import math
import re
from collections import Counter

DISCLAIMER = ('Это предварительная проверка извлечённых сведений, а не проверка подлинности. '
              'Подпись и печать необходимо сверить с оригиналом. '
              'Окончательное решение принимает сотрудник деканата.')
SYNONYMS = (
    ('подпись', 'подписать', 'автограф'),
    ('печать', 'штамп', 'печатный'),
    ('стоимость', 'цена', 'оплата'),
    ('фамилия', 'фио', 'имя'),
    ('отсутствует', 'нехватка', 'недостающий'),
)
STOP = {'какой', 'какие', 'найти', 'нужно', 'можно', 'пункт', 'прави', 'докум', 'полож', 'этого'}


def terms(text):
    return [w[:5] for w in re.findall(r'[а-яa-z]+', text.lower().replace('ё', 'е'))
            if len(w) >= 3 and w[:5] not in STOP]


def rank_clauses(query, clauses, limit=12):
    """BM25 with query-only expansion. Scores are relevance, never confidence."""
    if not clauses or not query.strip():
        return []
    refs = set(re.findall(r'\b\d+\.\d+\b', query))
    exact = [key for key in clauses if str(key) in refs]
    if exact:
        return [(key, 1.0) for key in exact[:limit]]
    words = set(terms(query))
    expanded = set(words)
    for group in SYNONYMS:
        family = set(terms(' '.join(group)))
        if words & family:
            expanded.update(family)
    if not expanded:
        return []
    corpus = {key:Counter(terms(text)) for key, text in clauses.items()}
    lengths = {key:sum(row.values()) for key, row in corpus.items()}
    average = sum(lengths.values()) / len(corpus) or 1
    frequencies = Counter(word for row in corpus.values() for word in row)
    ranked = []
    for key, row in corpus.items():
        score = 0.0
        for word in expanded:
            if not row[word]:
                continue
            idf = math.log1p((len(corpus)-frequencies[word]+.5)/(frequencies[word]+.5))
            weight = 1.0 if word in words else .65
            score += weight * idf * row[word] * 2.2 / (row[word] + 1.2*(.3+.7*lengths[key]/average))
        if score > 0:
            ranked.append((key, score))
    return sorted(ranked, key=lambda item: (-item[1], str(item[0])))[:limit]


def document_report(fields, config, rules, state='ready'):
    if state != 'ready' or not config:
        return {'available':False, 'disclaimer':DISCLAIMER, 'checks':[]}
    checks = []
    for spec in config['fields']:
        value = fields.get(spec['key'])
        present = value not in (None, '', 'не найдено', False)
        ref = str(spec.get('rule', ''))
        checks.append({'key':spec['key'], 'label':spec['label'], 'value':value,
                       'present':present, 'required':spec.get('required', True),
                       'rule':ref, 'quote':rules.get(ref),
                       'note':'Наличие графической отметки не подтверждает её подлинность.'
                       if spec['kind'] == 'boolean' else ''})
    required = [c for c in checks if c['required']]
    missing = [c['label'] for c in required if not c['present']]
    return {'available':True, 'required_count':len(required),
            'present_count':sum(c['present'] for c in required), 'missing':missing,
            'summary':'Не хватает обязательных сведений' if missing else 'Обязательные сведения найдены',
            'checks':checks, 'disclaimer':DISCLAIMER}
