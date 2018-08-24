# The source pdfs are located here - https://github.com/alphagov/notifications-utils/tree/master/tests/test_files


def file(filename):
    with open(filename, 'rb') as f:
        return f.read()


no_colour = file('tests/test_pdfs/no_colour.pdf')

blank_page = file('tests/test_pdfs/blank_page.pdf')

one_page_pdf = file('tests/test_pdfs/one_page_pdf.pdf')

multi_page_pdf = file('tests/test_pdfs/multi_page_pdf.pdf')

example_dwp_pdf = file('tests/test_pdfs/example_dwp_pdf.pdf')

not_pdf = file(__file__)

cmyk_image_pdf = file('tests/test_pdfs/cmyk_image.pdf')

cmyk_image_pdf = file('tests/test_pdfs/cmyk_image.pdf')

rgb_image_pdf = file('tests/test_pdfs/rgb_image.pdf')
