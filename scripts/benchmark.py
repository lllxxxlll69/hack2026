"""Run real Ollama inference on a manifest, then produce the organizer format."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.ai import answer, extract  # noqa: E402
from backend.logic import built_in_types, parse_rules, validate_fields  # noqa: E402


async def run(args):
    directory = args.data.resolve()
    manifest = json.loads((directory / 'documents.json').read_text(encoding='utf-8'))
    questions = json.loads((directory / 'questions.json').read_text(encoding='utf-8'))
    rules = parse_rules((directory / 'rules.md').read_text(encoding='utf-8'))
    types = built_in_types()
    output = {'version':'1.0', 'documents':[]}
    if args.resume and args.output.exists():
        output = json.loads(args.output.read_text(encoding='utf-8'))
    completed = {row['document_id'] for row in output['documents']}
    for index, row in enumerate(manifest):
        if args.ids and row['document_id'] not in args.ids:
            continue
        if args.limit and index >= args.limit:
            break
        if row['document_id'] in completed:
            continue
        relative = row['pdf'] if args.pdf else row['image']
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory):
            raise ValueError('Manifest path leaves dataset directory')
        selected = 'auto' if args.auto_type else row['document_type']
        kind, text, fields = await extract(path.read_bytes(), 'application/pdf' if args.pdf else 'image/png', types, selected)
        answers = []
        for question in questions:
            if question['document_id'] == row['document_id']:
                result = await answer(question['question'], fields, types[kind], rules)
                answers.append({'question_id':question['question_id'], **{k: result[k] for k in ('answerable','value','answer','sources')}})
        output['documents'].append({'document_id':row['document_id'], 'document_type':kind,
                                    'fields':fields, 'validation':validate_fields(fields, types[kind]), 'answers':answers})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'{index + 1}/{len(manifest)}: {row["document_id"]}', flush=True)
    print('Saved:', args.output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, default=ROOT / 'data/case')
    parser.add_argument('--output', type=Path, default=ROOT / 'output/results.json')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--pdf', action='store_true')
    parser.add_argument('--auto-type', action='store_true', help='Detect document type instead of using the manifest hint')
    parser.add_argument('--ids', nargs='+', help='Select document IDs for a smoke test')
    asyncio.run(run(parser.parse_args()))
