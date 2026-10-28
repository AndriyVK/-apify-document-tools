"""Local checks of src.frames. Usage (from the Actor folder): python -m tests.check <corpus_dir>

Generates scenes.mp4: 4 solid-colour scenes of 3 s each (black, white, red, yellow), 25 fps, GOP 2 s.
"""
import os
import subprocess
import sys
import tempfile

from PIL import Image

from src.frames import FrameError, contact_sheet, grab, plan_times, probe, select_frames

COLOURS = [(0, 0, 0), (255, 255, 255), (255, 0, 0), (255, 255, 0)]


def make_scenes(path):
    inputs = []
    for c in ('black', 'white', 'red', 'yellow'):
        inputs += ['-f', 'lavfi', '-t', '3', '-i', f'color=c={c}:s=640x360:r=25']
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *inputs, '-filter_complex', 'concat=n=4:v=1:a=0',
                    '-g', '50', '-pix_fmt', 'yuv420p', path], check=True)


def colour(path):
    with Image.open(path) as im:
        return im.convert('RGB').getpixel((im.width // 2, im.height // 2))


def near(a, b):
    return all(abs(x - y) < 40 for x, y in zip(a, b))


def main():
    d = sys.argv[1]
    bad = 0

    def check(name, cond, info=''):
        nonlocal bad
        bad += not cond
        print(f"{'OK ' if cond else 'BAD'} {name} {info}")

    with tempfile.TemporaryDirectory() as tmp:
        vid = os.path.join(tmp, 'scenes.mp4')
        make_scenes(vid)
        m = probe(vid)
        check('probe', abs(m['duration'] - 12) < 0.1 and m['width'] == 640 and m['fps'] == 25, str(m))
        times = plan_times('count', m['duration'], interval=0, count=4, timestamps=[], max_frames=100)
        check('count=4 times', [round(t, 1) for t in times] == [1.5, 4.5, 7.5, 10.5], str(times))
        cols = []
        for i, t in enumerate(times):
            dest = os.path.join(tmp, f'c{i}.png')
            check(f'grab {t}', grab(vid, t, dest, 'png', 0))
            cols.append(colour(dest))
        check('frame colours follow scenes', all(near(c, e) for c, e in zip(cols, COLOURS)), str(cols))
        times = plan_times('interval', m['duration'], interval=5, count=0, timestamps=[], max_frames=100)
        check('interval=5', times == [0, 5, 10], str(times))
        times = plan_times('timestamps', m['duration'], interval=0, count=0, timestamps=['0:04', '7.5', '99'],
                           max_frames=100)
        check('timestamps (past end dropped)', times == [4.0, 7.5], str(times))
        try:
            plan_times('timestamps', 12, interval=0, count=0, timestamps=['abc'], max_frames=10)
            check('bad timestamp rejected', False)
        except FrameError:
            check('bad timestamp rejected', True)
        os.makedirs(os.path.join(tmp, 's'))
        got = select_frames(vid, os.path.join(tmp, 's'), 'v', 'jpg', 320, 'scenes', 0.3, 100)
        check('scenes: start + 3 changes at 3/6/9 s', [round(t) for t, _ in got] == [0, 3, 6, 9], str([t for t, _ in got]))
        check('scenes: colours', [near(colour(f), c) for (_, f), c in zip(got, COLOURS)] == [True] * 4)
        check('maxWidth 320', Image.open(got[0][1]).width == 320)
        os.makedirs(os.path.join(tmp, 'k'))
        got = select_frames(vid, os.path.join(tmp, 'k'), 'v', 'webp', 0, 'keyframes', 0, 100)
        ref = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-skip_frame', 'nokey', '-show_entries',
                              'frame=pts_time', '-of', 'csv=p=0', vid], capture_output=True, text=True).stdout.split()
        check('keyframes = ffprobe keyframes', [round(t, 2) for t, _ in got] == [round(float(x.strip(',')), 2) for x in ref if x.strip(',')]
              and len(got) >= 2, f'{[t for t, _ in got]} vs {ref}')
        os.makedirs(os.path.join(tmp, 'l'))
        got = select_frames(vid, os.path.join(tmp, 'l'), 'v', 'jpg', 0, 'keyframes', 0, 2)
        check('maxFrames limits selection', len(got) == 2)
        sheet = os.path.join(tmp, 'sheet.jpg')
        contact_sheet([(1.5, os.path.join(tmp, f'c{i}.png')) for i in range(4)], sheet)
        check('contact sheet', Image.open(sheet).size[0] > 1000)
        real = probe(f'{d}/video-en.mp4')
        check('real mp4 probe', real['width'] == 320 and real['duration'] > 40, str(real))
        check('real mp4 grab', grab(f'{d}/video-en.mp4', 20, os.path.join(tmp, 'r.jpg'), 'jpg', 0))
        for name in ('speech-en.mp3', 'broken-file.pdf'):
            try:
                probe(f'{d}/{name}')
                check(f'{name} rejected', False)
            except FrameError as e:
                check(f'{name} rejected', True, str(e))
    print('FAILED' if bad else 'ALL OK', bad)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
