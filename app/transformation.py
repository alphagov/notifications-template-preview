#!/usr/bin/env python
import fitz
import subprocess


class Logo():
    def __init__(self, filename):
        self.raster = '{}.png'.format(filename)
        self.vector = '{}.svg'.format(filename)


def does_pdf_contain_cmyk(data):
    doc = fitz.open(stream=data, filetype="pdf")
    for i in range(len(doc)):
        for img in doc.getPageImageList(i):
            xref = img[0]
            pix = fitz.Pixmap(doc, xref)
            if "CMYK" in pix.colorspace.__str__():
                return True
    return False


def convert_pdf_to_cmyk(input_data):
    gs_process = subprocess.Popen(
        [
            'gs',
            '-q',
            '-o',
            '-',
            '-dCompatibilityLevel=1.7',
            '-sDEVICE=pdfwrite',
            '-sColorConversionStrategy=CMYK',
            '-sSourceObjectICC=app/ghostscript/control.txt',
            '-dBandBufferSpace=100000000',
            '-dBufferSpace=100000000',
            '-dMaxPatternBitmap=1000000',
            '-c 100000000 setvmthreshold -f',
            '-'
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = gs_process.communicate(input=input_data)
    if gs_process.returncode != 0:
        raise Exception('ghostscript process failed with return code: {}\nstdout: {}\nstderr:{}'
                        .format(gs_process.returncode, stdout, stderr))
    return stdout
