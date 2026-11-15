"""Unit tests for OCR text layout (no Tesseract needed). Run: python -m tests.test_layout"""
from src.convert import _join_broken


def test_join_broken():
    assert _join_broken('Склад отримав палети протягом\n\nтретього кварталу.') == \
        'Склад отримав палети протягом третього кварталу.'
    # a finished sentence, a heading before a capitalised paragraph and a table stay apart
    assert _join_broken('Кінець речення.\n\nнове') == 'Кінець речення.\n\nнове'
    assert _join_broken('Звіт про постачання\n\nСклад у Львові') == 'Звіт про постачання\n\nСклад у Львові'
    assert _join_broken('текст\n\n| a | b |') == 'текст\n\n| a | b |'
    assert _join_broken('перелік,\n\nдалі') == 'перелік, далі'
    assert _join_broken('отримав 1240\n\nпалет') == 'отримав 1240 палет'


if __name__ == '__main__':
    test_join_broken()
    print('test_layout: OK')
