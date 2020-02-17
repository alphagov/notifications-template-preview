from flask import current_app
from PyPDF2 import PdfFileReader


def contains_unembedded_fonts(pdf_data):
    """
    Code adapted from https://gist.github.com/tiarno/8a2995e70cee42f01e79

    :param BytesIO pdf_data: a file-like object containing the pdf
    :return boolean: If any fonts are contained that are not embedded.
    """
    def walk(obj, fnt, emb):
        '''
        If there is a key called 'BaseFont', that is a font that is used in the document.
        If there is a key called 'FontName' and another key in the same dictionary object
        that is called 'FontFilex' (where x is null, 2, or 3), then that fontname is
        embedded.

        We create and add to two sets, fnt = fonts used and emb = fonts embedded.
        '''
        if hasattr(obj, 'keys'):
            fontkeys = {'/FontFile', '/FontFile2', '/FontFile3'}
            if '/BaseFont' in obj:
                fnt.add(obj['/BaseFont'])
            if '/FontName' in obj:
                if any(x in obj for x in fontkeys):  # test to see if there is FontFile
                    emb.add(obj['/FontName'])

            for k in obj.keys():
                walk(obj[k], fnt, emb)

    pdf = PdfFileReader(pdf_data)
    fonts = set()
    embedded = set()
    for page in pdf.pages:
        obj = page.getObject()
        walk(obj['/Resources'], fonts, embedded)

    unembedded = fonts - embedded
    if unembedded:
        current_app.logger.info(f'Found unembedded fonts {unembedded}')
    return unembedded


def remove_embedded_fonts(pdf_data):
    return pdf_data
