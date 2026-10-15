"""Diagnostic for the vision model on zoomed signature/stamp areas."""
import asyncio
import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.ai import chat  # noqa: E402


async def main():
    for document_id in sys.argv[1:]:
        with Image.open(ROOT / 'data/case/documents' / (document_id + '.png')) as image:
            lower = image.crop((0, int(image.height * .55), image.width, image.height))
            out = io.BytesIO()
            lower.save(out, format='PNG')
        schema = {'type':'object','properties':{'signature_present':{'type':'boolean'},'seal_present':{'type':'boolean'}},'required':['signature_present','seal_present'],'additionalProperties':False}
        result = await chat('На фрагменте документа проверь реальную графическую подпись '
                            '(неровный росчерк ручкой) и рисунок оттиска печати. Если видна '
                            'только пустая линия и типографский текст «Подпись сотрудника» '
                            'или «М.П.», отметки отсутствуют. Не считай подписью слова. '
                            'Условные синие учебные рисунки подписи и печати считаются отметками.',
                            schema, images=[out.getvalue()])
        print(document_id, result, flush=True)


if __name__ == '__main__':
    asyncio.run(main())
