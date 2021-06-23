#!/usr/bin/env python
import subprocess
from io import BytesIO

import fitz
from flask import current_app

from app import InvalidRequest


def _does_pdf_contain_colorspace(colourspace, data):
    doc = fitz.open(stream=data, filetype="pdf")
    for i in range(len(doc)):
        try:
            page = doc.getPageImageList(i)
        except RuntimeError:
            current_app.logger.warning("Fitz couldn't read page info for page {}".format(i + 1))
            raise InvalidRequest("Invalid PDF on page {}".format(i + 1))
        for img in page:
            xref = img[0]
            pix = fitz.Pixmap(doc, xref)
            if colourspace in pix.colorspace.__str__():
                data.seek(0)
                return True
    data.seek(0)
    return False


def does_pdf_contain_cmyk(data):
    return _does_pdf_contain_colorspace("CMYK", data)


def does_pdf_contain_rgb(data):
    return _does_pdf_contain_colorspace("RGB", data)


def convert_pdf_to_cmyk(input_data):
    gs_process = subprocess.Popen(
        [
            'gs',
            '-q',  # quiet on STDOUT
            '-o', '-',  # write to STDOUT
            '-dCompatibilityLevel=1.7',  # DVLA require PDF v1.7 (see edaad254)
            '-sDEVICE=pdfwrite',  # generate PDF output
            '-sColorConversionStrategy=CMYK',
            '-sSourceObjectICC=app/ghostscript/control.txt',  # custom mappings to ensure black -> black (see a890f9f0)
            '-dBandBufferSpace=100000000',  # make it faster (see 14233fb0)
            '-dBufferSpace=100000000',  # make it faster (see 14233fb0)
            '-dMaxPatternBitmap=1000000',  # make it faster (see 14233fb0)
            '-dAutoRotatePages=/None',  # stop inferring page rotation (see 250b205b)
            '-c', '100000000 setvmthreshold',  # make it faster (see 14233fb0)
            '-f', '-'  # read from STDIN
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = gs_process.communicate(input=input_data.read())
    if gs_process.returncode != 0:
        raise Exception('ghostscript cmyk transformation failed with return code: {}\nstdout: {}\nstderr:{}'
                        .format(gs_process.returncode, stdout, stderr))
    return BytesIO(stdout)
