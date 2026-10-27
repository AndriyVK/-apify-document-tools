"""Office/HTML/image -> PDF with LibreOffice, one soffice call per document family."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

# Family -> LibreOffice PDF export filter
FAMILIES = {
    'writer': ('writer_pdf_Export', {'.doc', '.docx', '.docm', '.dot', '.dotx', '.odt', '.ott', '.rtf', '.txt',
                                     '.wpd', '.html', '.htm', '.xhtml', '.md'}),
    'calc': ('calc_pdf_Export', {'.xls', '.xlsx', '.xlsm', '.xlsb', '.ods', '.ots', '.csv'}),
    'impress': ('impress_pdf_Export', {'.ppt', '.pptx', '.pptm', '.pps', '.ppsx', '.odp', '.otp'}),
    'draw': ('draw_pdf_Export', {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tif', '.tiff', '.webp', '.svg', '.odg',
                                 '.vsd', '.vsdx'}),
}
EXT_FAMILY = {ext: fam for fam, (_, exts) in FAMILIES.items() for ext in exts}
SUPPORTED_EXT = set(EXT_FAMILY)

BY_CONTENT_TYPE = {
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
    'application/msword': '.doc', 'application/vnd.ms-excel': '.xls', 'application/vnd.ms-powerpoint': '.ppt',
    'application/vnd.oasis.opendocument.text': '.odt', 'application/vnd.oasis.opendocument.spreadsheet': '.ods',
    'application/vnd.oasis.opendocument.presentation': '.odp', 'application/rtf': '.rtf', 'text/rtf': '.rtf',
    'text/html': '.html', 'text/plain': '.txt', 'text/csv': '.csv', 'image/png': '.png', 'image/jpeg': '.jpg',
    'image/tiff': '.tiff', 'image/gif': '.gif', 'image/webp': '.webp', 'image/svg+xml': '.svg',
}


class ConversionError(Exception):
    pass


def detect_ext(path: str, name_hint: str = '', content_type: str = '') -> str:
    for candidate in (name_hint, path):
        ext = os.path.splitext(candidate.split('?')[0])[1].lower()
        if ext in SUPPORTED_EXT:
            return ext
    ct = content_type.split(';')[0].strip().lower()
    if ct in BY_CONTENT_TYPE:
        return BY_CONTENT_TYPE[ct]
    with open(path, 'rb') as f:
        head = f.read(8)
    if head.startswith(b'%PDF'):
        raise ConversionError('the file is already a PDF')
    if head.startswith(b'\x89PNG'):
        return '.png'
    if head.startswith(b'\xff\xd8'):
        return '.jpg'
    if head.startswith(b'{\\rtf'):
        return '.rtf'
    if head.startswith(b'\xd0\xcf\x11\xe0'):
        return '.doc'  # OLE container (doc/xls/ppt): LibreOffice detects the real type itself
    raise ConversionError(f'unsupported file type (name {name_hint!r}, content type {content_type!r})')


ZIP_EXT = {'.docx', '.docm', '.dotx', '.xlsx', '.xlsm', '.xlsb', '.pptx', '.pptm', '.ppsx', '.odt', '.ott', '.ods',
           '.ots', '.odp', '.otp', '.odg', '.vsdx'}
OLE_EXT = {'.doc', '.dot', '.xls', '.ppt', '.pps', '.vsd'}


def check_signature(path: str, ext: str) -> None:
    """LibreOffice imports unreadable binaries as plain text; refuse them instead of producing (and charging for) junk."""
    with open(path, 'rb') as f:
        head = f.read(8)
    if ext in ZIP_EXT and not head.startswith(b'PK'):
        raise ConversionError(f'not a valid {ext} file (damaged or wrong extension)')
    if ext in OLE_EXT and not head.startswith(b'\xd0\xcf\x11\xe0') and not head.startswith(b'PK'):
        raise ConversionError(f'not a valid {ext} file (damaged or wrong extension)')
    if ext == '.rtf' and not head.startswith(b'{\\rtf'):
        raise ConversionError('not a valid .rtf file (damaged or wrong extension)')


def _filter(family: str, pdfa: bool) -> str:
    name = FAMILIES[family][0]
    if pdfa:  # PDF/A-2b
        return f'pdf:{name}:{{"SelectPdfVersion":{{"type":"long","value":"2"}}}}'
    return f'pdf:{name}'


def _soffice(paths: list[str], family: str, outdir: str, pdfa: bool, timeout: int) -> None:
    soffice = shutil.which('soffice') or shutil.which('libreoffice')
    if not soffice:
        raise ConversionError('LibreOffice is not available')
    profile = tempfile.mkdtemp(prefix='lo-profile-')
    try:
        subprocess.run([soffice, f'-env:UserInstallation=file://{profile}', '--headless', '--norestore',
                        '--convert-to', _filter(family, pdfa), '--outdir', outdir, *paths],
                       capture_output=True, timeout=timeout)
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def convert_all(inputs: list[tuple[str, str]], outdir: str, *, pdfa: bool = False) -> dict[str, str | ConversionError]:
    """inputs: (path, ext) with unique base names. Returns path -> output PDF path or ConversionError."""
    results: dict[str, str | ConversionError] = {}
    groups: dict[str, list[str]] = {}
    for path, ext in inputs:
        groups.setdefault(EXT_FAMILY[ext], []).append(path)
    for family, paths in groups.items():
        try:
            _soffice(paths, family, outdir, pdfa, timeout=60 + 20 * len(paths))
        except subprocess.TimeoutExpired:
            # One slow or broken file must not sink the batch: retry one by one
            for p in paths:
                if not os.path.exists(_out(p, outdir)):
                    try:
                        _soffice([p], family, outdir, pdfa, timeout=180)
                    except subprocess.TimeoutExpired:
                        results[p] = ConversionError('conversion timed out (file too large or damaged)')
        for p in paths:
            if p in results:
                continue
            out = _out(p, outdir)
            results[p] = out if os.path.exists(out) and os.path.getsize(out) > 0 else ConversionError(
                'LibreOffice could not open this file (damaged, password-protected or not the stated format)')
    return results


def _out(path: str, outdir: str) -> str:
    return os.path.join(outdir, os.path.splitext(os.path.basename(path))[0] + '.pdf')


def pdf_pages(path: str) -> int:
    from pypdf import PdfReader
    return len(PdfReader(path).pages)


def merge(paths: list[str], dest: str) -> int:
    from pypdf import PdfWriter
    writer = PdfWriter()
    for p in paths:
        writer.append(p)
    with open(dest, 'wb') as f:
        writer.write(f)
    return len(writer.pages)
