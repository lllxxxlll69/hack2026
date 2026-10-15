import json

import pytest

from backend.config import ROOT
from backend.logic import (MISSING, built_in_types, deterministic_answer, normalize_fields,
                           parse_rules, requests_handoff, unknown_answer, validate_fields)


def test_validation_and_factual_answers_for_every_open_case():
    """References are test fixtures only, never inputs to OCR or runtime inference."""
    reference = json.loads((ROOT / 'data/case/reference_results.json').read_text(encoding='utf-8'))
    questions = {q['question_id']:q['question'] for q in json.loads((ROOT / 'data/case/questions.json').read_text(encoding='utf-8'))}
    rules = parse_rules((ROOT / 'data/case/rules.md').read_text(encoding='utf-8'))
    types = built_in_types()
    for doc in reference['documents']:
        config, fields = types[doc['document_type']], doc['fields']
        actual = validate_fields(fields, config)
        assert actual['status'] == doc['validation']['status']
        assert set(actual['sources']) == set(doc['validation']['sources'])
        assert set(actual['missing_fields']) == set(doc['validation']['missing_fields'])
        for expected in doc['answers']:
            result = deterministic_answer(questions[expected['question_id']], fields, config, rules) or unknown_answer()
            assert result['answerable'] == expected['answerable'], expected['question_id']
            assert result['value'] == expected['value'], expected['question_id']
            assert set(result['sources']) == set(expected['sources']), expected['question_id']


def test_normalization_does_not_invent_missing_marks_or_dates():
    config = built_in_types()['academic_leave_application']
    fields = normalize_fields({'signature_present':'false', 'course':'2 курс',
                               'leave_start':'1 сентября 2026 года', 'leave_end':'31.02.2027'}, config)
    assert fields['signature_present'] is False
    assert fields['course'] == '2'
    assert fields['leave_start'] == '2026-09-01'
    assert fields['leave_end'] == MISSING
    assert fields['student_name'] == MISSING


def test_handoff_request():
    assert requests_handoff('Переведи меня на деканат')
    assert requests_handoff('Хочу поговорить с сотрудником')
    assert not requests_handoff('Кто принимает окончательное решение?')


@pytest.mark.asyncio
async def test_unknown_evidence_cannot_become_a_rule_or_field(monkeypatch):
    from backend import ai
    async def invalid(*args, **kwargs):
        return {'kind':'rules', 'field':'', 'rules':['999.7']}
    monkeypatch.setattr(ai, 'chat', invalid)
    result = await ai.answer('Какова стоимость?', {}, None, {'1.3':'Решение принимает сотрудник.'})
    assert result['answerable'] is False
    assert result['sources'] == []


def test_duplicate_rule_numbers_rejected():
    with pytest.raises(ValueError):
        parse_rules('7.1. Первое\n7.1. Второе')
