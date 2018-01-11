#!/usr/bin/env python
import subprocess


class Logo():
    def __init__(self, raster, vector=None):
        self.raster = raster
        self.vector = vector or self.raster


def convert_pdf_to_cmyk(input_data):
    stdout, _ = subprocess.Popen(
        [
            'gs',
            '-o',
            '-',
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
