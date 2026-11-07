"""python -m unittest discover -s tests (from the Actor folder)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.crosscheck import compare  # noqa: E402

# Storm Austen, BBC News on TikTok, 7.11.2026: whisper-large-v3 against whisper-large-v3-turbo
PRIMARY = [{'start': 0.0, 'end': 7.0, 'text': 'The full force of Storm Austin has arrived here in Newquay and Cornwall. '
            'We are now seeing gusts of wind of 17, even 18 miles an hour.'},
           {'start': 7.0, 'end': 16.0, 'text': 'Now it is the south west around Devon.'},
           {'start': 21.0, 'end': 28.0, 'text': 'The winds will move east with drought in the morning.'}]
OTHER = [{'start': 0.0, 'end': 7.3, 'text': "The full force of Storm Austin has arrived here in Newquay and Cornwall. "
          "We're now seeing just a room of 70, even 80 miles an hour."},
         {'start': 7.9, 'end': 15.8, 'text': "Now, it's the southwest around Devon."},
         {'start': 21.4, 'end': 28.7, 'text': 'The winds will move east throughout the morning.'}]


class CrossCheck(unittest.TestCase):
    def test_bbc(self):
        r = compare(PRIMARY, OTHER)
        self.assertEqual([(d['text'], d['other'], d['numbers'], d['start']) for d in r['differences']],
                         [('gusts of wind of 17 even 18', 'just a room of 70 even 80', True, 0.0),
                          ('with drought in', 'throughout', False, 21.0)])
        self.assertTrue(0.8 < r['agreement'] < 1)

    def test_same_and_empty(self):
        self.assertEqual(compare(PRIMARY, PRIMARY), {'agreement': 1.0, 'differences': []})
        self.assertEqual(compare([], []), {'agreement': 1.0, 'differences': []})
        self.assertEqual(compare(PRIMARY, [])['agreement'], 0.0)
        only_other = compare([], OTHER)['differences']
        self.assertEqual((only_other[0]['start'], only_other[0]['end']), (0.0, 28.7))

    def test_repeated_words_and_ukrainian(self):
        r = compare([{'start': 0, 'end': 3, 'text': 'Це природньо. Це природньо.'}],
                    [{'start': 0, 'end': 3, 'text': 'Це природно. Це природно.'}])
        self.assertEqual([d['text'] for d in r['differences']], ['природньо Це природньо'])

    def test_repeated_passage(self):
        # the same sentence read three times (speech-en.mp3): only the second reading differs
        line = 'The warehouse in Lviv received 1,240 pallets of building materials during the third quarter.'
        primary = [{'start': 15.0 * k, 'end': 15.0 * k + 14, 'text': line} for k in range(3)]
        other = [dict(s) for s in primary]
        other[1] = {'start': 15.4, 'end': 29.0, 'text': line.replace('in Lviv', 'in Elvive')}
        other[0] = {'start': 0.3, 'end': 14.2, 'text': line}
        r = compare(primary, other)
        self.assertEqual([(d['text'], d['other'], d['start']) for d in r['differences']], [('Lviv', 'Elvive', 15.0)])
        self.assertGreater(r['agreement'], 0.95)

    def test_long_recording_is_fast(self):
        import random
        import time
        rnd = random.Random(1)
        words = [rnd.choice(['one', 'two', 'three', 'Lviv', 'Kyiv', 'and', 'the', 'we', 'pallets']) for _ in range(9000)]
        primary = [{'start': k * 4.0, 'end': k * 4.0 + 4, 'text': ' '.join(words[k * 10:k * 10 + 10])} for k in range(900)]
        other = [dict(s) for s in primary]
        other[450] = {**other[450], 'text': 'something else entirely'}
        t0 = time.monotonic()
        r = compare(primary, other)
        self.assertLess(time.monotonic() - t0, 20)
        self.assertEqual(len(r['differences']), 1)
        self.assertIn(r['differences'][0]['start'], (1796.0, 1800.0))  # a tie on random words

    def test_number_spelling(self):
        r = compare([{'start': 0, 'end': 6, 'text': 'Lviv received 1240 pallets, up by 12%.'}],
                    [{'start': 0, 'end': 6, 'text': 'Lviv received 1,240 pallets, up by twelve percent.'}])
        self.assertEqual(r, {'agreement': 1.0, 'differences': []})
        r = compare([{'start': 0, 'end': 4, 'text': 'скоротилися на 12 відсотків'}],
                    [{'start': 0, 'end': 4, 'text': 'скоротилися на 12%'}])
        self.assertEqual(r['differences'], [])


if __name__ == '__main__':
    unittest.main()
