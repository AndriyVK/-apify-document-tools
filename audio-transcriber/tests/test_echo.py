"""Whisper writing out its prompt instead of the speech (audio-transcriber run fqodYm9Ivps9fXH5B, 7.11.2026)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.transcribe import _echoed, _prompt, _prompt_words  # noqa: E402

WORDS = _prompt_words(_prompt(None, 'en') + ' ' + _prompt(None, 'uk'))
ECHO = ('Кијов, Львів, Карків, Суми, Сменијев, Одеса, Деньмир, Наркијов, Запорижжя, Винна, Ортампон, Харків, '
        'Семенјев, Семенјев.')


def res(texts, language='english'):
    return {'language': language, 'segments': [{'text': t} for t in texts]}


class Echo(unittest.TestCase):
    def test_echo_found(self):
        self.assertTrue(_echoed(res([ECHO]), WORDS))
        self.assertTrue(_echoed(res([ECHO], 'ukrainian'), WORDS))
        self.assertTrue(_echoed(res(['Kyiv, Lviv, Kharkiv, Odesa.', 'Dnipro, Zaporizhzhia, Vinnytsia.', 'Hello.']), WORDS))

    def test_speech_kept(self):
        for text, lang in [('The warehouse in Lviv received 1240 pallets of building materials.', 'english'),
                           ('Kyiv, Lviv and Kharkiv were hit overnight, officials said.', 'english'),
                           ('Склад у Львові отримав 1240 палет будівельних матеріалів.', 'ukrainian'),
                           ('Я поїхав у Київ, потім у Львів і Харків.', 'ukrainian'),
                           ('Захист мови є частиною національної безпеки.', 'ukrainian')]:
            self.assertFalse(_echoed(res([text], lang), WORDS), text)
        self.assertFalse(_echoed(res([ECHO]), set()))

    def test_no_place_names_without_language(self):
        self.assertEqual(_prompt(None, None), '')
        self.assertEqual(_prompt('Kyivstar', None), 'Kyivstar')
        self.assertIn('Львів', _prompt(None, 'uk'))


if __name__ == '__main__':
    unittest.main()
