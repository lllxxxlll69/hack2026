from backend.evidence import DISCLAIMER, document_report, rank_clauses


def test_search_expands_synonyms_but_returns_only_existing_clauses():
    rules = {'3.2':'Обязательна подпись сотрудника.', '3.3':'Обязательна печать вуза.',
             '4.1':'Нужны даты начала и окончания отпуска.'}
    assert rank_clauses('автограф', rules)[0][0] == '3.2'
    assert rank_clauses('штамп', rules)[0][0] == '3.3'
    assert rank_clauses('пункт 4.1', rules) == [('4.1', 1.0)]
    assert rank_clauses('абракадабра', rules) == []
    assert rank_clauses('', rules) == []


def test_report_does_not_invent_missing_values_or_quotes():
    config = {'fields':[
        {'key':'name', 'label':'ФИО', 'kind':'string', 'required':True, 'rule':'3.1'},
        {'key':'seal', 'label':'Печать', 'kind':'boolean', 'required':True, 'rule':'3.3'},
        {'key':'note', 'label':'Комментарий', 'kind':'string', 'required':False, 'rule':'9.9'}]}
    report = document_report({'name':'Тестовый студент', 'seal':False}, config, {'3.1':'ФИО обязательно.'})
    assert report['present_count'] == 1
    assert report['required_count'] == 2
    assert report['missing'] == ['Печать']
    assert report['checks'][0]['quote'] == 'ФИО обязательно.'
    assert report['checks'][1]['quote'] is None
    assert report['checks'][1]['note']
    assert report['checks'][2]['value'] is None
    assert report['disclaimer'] == DISCLAIMER
    assert 'confidence' not in report
    assert not document_report({}, config, {}, 'processing')['available']
    assert not document_report({}, None, {})['available']
