# These string constants are a copy of the base64 constants in
# https://github.com/alphagov/notifications-utils/blob/master/tests/pdf_consts.py
# The source pdfs are located here - https://github.com/alphagov/notifications-utils/tree/master/tests/test_files
from base64 import b64encode


def file_to_b64(filename):
    with open(filename, 'rb') as f:
        return b64encode(f.read())


no_colour = file_to_b64('tests/test_pdfs/no_colour.pdf')

blank_page = file_to_b64('tests/test_pdfs/blank_page.pdf')

one_page_pdf = file_to_b64('tests/test_pdfs/one_page_pdf.pdf')

multi_page_pdf = file_to_b64('tests/test_pdfs/multi_page_pdf.pdf')

example_dwp_pdf = file_to_b64('tests/test_pdfs/example_dwp_pdf.pdf')

not_pdf = file_to_b64(__file__)
