import base64
import io

import httpx
import pytest
from PIL import Image

from backend import ai
from backend.logic import built_in_types


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['qwen3-vl:2b', 'qwen3-vl:2b-instruct'])
async def test_ollama_thinking_and_instruct_protocol_and_no_proxy(monkeypatch, model):
    sent = {}
    real_client = httpx.AsyncClient

    def handler(request):
        import json
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={'message':{'content':'{"ok":true}'}})

    def client(**kwargs):
        assert kwargs['trust_env'] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(ai.httpx, 'AsyncClient', client)
    result = await ai.chat('Прочитай', {'type':'object'}, images=[b'image-bytes'], model=model)
    assert result == {'ok':True}
    assert sent['model'] == model
    if model.endswith('instruct'):
        assert len(sent['messages']) == 2
        assert sent['messages'][-1]['role'] == 'user'
    else:
        assert sent['messages'][-1] == {'role':'assistant', 'content':'<think>\n\n</think>\n\n'}
    assert sent['messages'][1]['images'] == [base64.b64encode(b'image-bytes').decode()]


@pytest.mark.asyncio
async def test_extraction_uses_image_and_schema_not_reference_values(monkeypatch):
    observed = []

    async def chat(prompt, schema, images=None, **kwargs):
        observed.append((schema, images))
        return {'document_type':'study_certificate', 'text':'Петров Пётр Петрович',
                'fields':{'student_name':'Петров Пётр Петрович','issue_date':'10.10.2026','signature_present':False}}
    monkeypatch.setattr(ai, 'chat', chat)
    image = io.BytesIO()
    Image.new('RGB', (100, 100), 'white').save(image, format='PNG')
    kind, text, fields = await ai.extract(image.getvalue(), 'image/png', built_in_types())
    assert kind == 'study_certificate'
    assert fields['student_name'] == 'Петров Пётр Петрович'
    assert fields['issue_date'] == '2026-10-10'
    assert fields['seal_present'] is False
    assert fields['signature_present'] is False
    assert observed[0][1][0].startswith(b'\x89PNG')
    assert 'unknown' in observed[0][0]['properties']['document_type']['enum']
    assert observed[1][0]['properties']['document_type']['const'] == 'study_certificate'
    assert observed[1][0]['properties']['fields']['required']


@pytest.mark.asyncio
async def test_unknown_type_stops_before_field_extraction(monkeypatch):
    calls = []

    async def classify(*args, **kwargs):
        calls.append(args)
        return {'document_type':'unknown'}
    monkeypatch.setattr(ai, 'chat', classify)
    buffer = io.BytesIO()
    Image.new('RGB', (100, 100), 'white').save(buffer, format='PNG')
    with pytest.raises(ValueError, match='определить тип'):
        await ai.extract(buffer.getvalue(), 'image/png', built_in_types())
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_manual_type_has_fixed_schema_without_unknown_branch(monkeypatch):
    calls = []

    async def extract(*args, **kwargs):
        calls.append(args[1])
        return {'document_type':'internship_certificate', 'fields':{}, 'lines':[]}
    monkeypatch.setattr(ai, 'chat', extract)
    buffer = io.BytesIO()
    Image.new('RGB', (100, 100), 'white').save(buffer, format='PNG')
    kind, _, fields = await ai.extract(buffer.getvalue(), 'image/png', built_in_types(), 'internship_certificate')
    assert kind == 'internship_certificate'
    assert len(calls) == 1
    assert calls[0]['properties']['document_type'] == {'const':'internship_certificate'}
    assert fields['student_name'] == 'не найдено'
