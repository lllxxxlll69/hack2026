import io

import cv2
import numpy as np
from PIL import Image

from backend.ai import image_png, mark_regions


def png(array):
    stream = io.BytesIO()
    Image.fromarray(array).save(stream, format='PNG')
    return stream.getvalue()


def test_empty_signature_line_is_not_a_signature():
    image = np.full((700, 1100, 3), 255, dtype=np.uint8)
    cv2.line(image, (100, 500), (500, 500), (50, 50, 50), 1)
    candidates = mark_regions(image_png(png(image)))
    assert candidates['signature_present'] == []
    assert candidates['seal_present'] == []


def test_region_proposals_use_graphical_evidence():
    image = np.full((700, 1100, 3), 255, dtype=np.uint8)
    cv2.circle(image, (900, 500), 75, (30, 70, 140), 3)
    cv2.circle(image, (900, 500), 64, (30, 70, 140), 3)
    points = np.array([[100,500],[130,480],[155,515],[170,480],[188,519],[213,478],[240,510],[275,485],[320,505]])
    cv2.polylines(image, [points], False, (30,70,140), 3)
    candidates = mark_regions(image_png(png(image)))
    assert candidates['signature_present']
    assert candidates['seal_present']
