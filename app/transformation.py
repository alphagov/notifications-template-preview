#!/usr/bin/env python
import subprocess


class Logo():
    def __init__(self, filename):
        self.raster = '{}.png'.format(filename)
        self.vector = '{}.svg'.format(filename)


def convert_pdf_to_cmyk(input_data):
    stdout, _ = subprocess.Popen(
        [
            'gs',
            '-q',
            '-o',
            '-',
            '-dCompatibilityLevel=1.7',
            '-sDEVICE=pdfwrite',
            '-sColorConversionStrategy=CMYK',
            '-sSourceObjectICC=app/ghostscript/control.txt',
            '-'
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).communicate(input=input_data)
    return stdout
