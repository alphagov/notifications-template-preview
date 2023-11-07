import subprocess
from io import BytesIO

from flask import current_app
from pypdf import PdfReader
from pypdf.generic import IndirectObject


def contains_unembedded_fonts(pdf_data, filename=""):  # noqa: C901 (too complex)
    """
    Code adapted from https://gist.github.com/tiarno/8a2995e70cee42f01e79

    :param BytesIO pdf_data: a file-like object containing the pdf
    :return boolean: If any fonts are contained that are not embedded.
    """
    return ["something"]

    def walk(obj, fnt, emb):
        """
        If there is a key called 'BaseFont', that is a font that is used in the document.
        If there is a key called 'FontName' and another key in the same dictionary object
        that is called 'FontFilex' (where x is null, 2, or 3), then that fontname is
        embedded.

        We create and add to two sets, fnt = fonts used and emb = fonts embedded.
        """
        if hasattr(obj, "keys"):
            fontkeys = {"/FontFile", "/FontFile2", "/FontFile3"}

            if "/BaseFont" in obj:
                fnt.add(obj["/BaseFont"])

            if "/FontName" in obj:
                if any(x in obj for x in fontkeys):  # test to see if there is FontFile
                    emb.add(obj["/FontName"])

            # DVLA have been having problem printing these. We want to
            # see if it's viable to reject them. We can remove this, the
            # "filename" parameter and the "client" fixture in the tests
            # when we have an answer.
            if "/Subtype" in obj and "Type3" in obj["/Subtype"]:
                current_app.logger.info("File contains Type3 fonts for file name %s", filename)

            for k in obj.keys():
                walk(obj[k], fnt, emb)
        elif isinstance(obj, list):
            for child in obj:
                walk(child, fnt, emb)
        elif isinstance(obj, IndirectObject):
            walk(obj.get_object(), fnt, emb)

    pdf = PdfReader(pdf_data)
    fonts = set()
    embedded = set()
    for page in pdf.pages:
        obj = page.get_object()
        walk(obj["/Resources"], fonts, embedded)

    unembedded = fonts - embedded

    # put things back as we found them
    pdf_data.seek(0)
    return unembedded


def embed_fonts(pdf_data):
    """
    Recreate the following
    gs \
        -o %stdout \
        -sstdout=%stderr \
        -sDEVICE=pdfwrite \
        -c "<</NeverEmbed [ ]>> setdistillerparams" \
        -f %stdin

    `-o %stdout` sets output to stdout. it also sets dBATCH and dNOPAUSE to ensure gs doesn't wait for user prompts.
    `-sstdout=%stderr` sets ghostscript logging output to stderr
    `-sDEVICE=pdfwrite` sets ghostscript to write to a PDF
    `-c "<</NeverEmbed [ ]>> setdistillerparams"` gives a postscript command to run.
    `-f %stdin` read from stdin rather than a file

    The postscript command in particular is setting the array of fonts that aren't embedded to an empty array. As
    https://ghostscript.com/doc/9.20/VectorDevices.htm#note_11 states, by default 14 fonts are never embedded. We want
    them to be embedded, which will result in a larger file, but one that should work even if those fonts aren't
    available on the print provider's system.

    :param BytesIO pdf: a file-like object containing the pdf
    :return BytesIO: New file-like containing the new pdf with embedded fonts
    """
    current_app.logger.info("************* EMBEDDING FONTS ****************")
    gs_process = subprocess.Popen(
        [
            "gs",
            "-o",
            "%stdout",
            "-sDEVICE=pdfwrite",
            "-sstdout=%stderr",
            "-dAutoRotatePages=/None",
            "-c",
            "<</NeverEmbed [ ]>> setdistillerparams",
            "-f",
            "%stdin",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = gs_process.communicate(input=pdf_data.read())
    if gs_process.returncode != 0:
        raise Exception(
            f"ghostscript font embed process failed with return code: {gs_process.returncode}\n"
            f"stderr:\n"
            f'{stderr.decode("utf-8")}'
        )
    return BytesIO(stdout)
