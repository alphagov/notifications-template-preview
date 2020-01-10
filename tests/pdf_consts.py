# The source pdfs are located here - https://github.com/alphagov/notifications-utils/tree/master/tests/test_files


def file(filename):
    with open(filename, 'rb') as f:
        return f.read()


a3_size = file('tests/test_pdfs/a3_size.pdf')

a5_size = file('tests/test_pdfs/a5_size.pdf')

address_block_repeated_on_second_page = file('tests/test_pdfs/address_block_repeated_on_second_page.pdf')

address_margin = file('tests/test_pdfs/address_margin.pdf')

blank_page = file('tests/test_pdfs/blank_page.pdf')

blank_with_address = file('tests/test_pdfs/blank_with_address.pdf')

cmyk_and_rgb_images_in_one_pdf = file('tests/test_pdfs/cmyk_and_rgb_in_one_pdf.pdf')

cmyk_image_pdf = file('tests/test_pdfs/cmyk_image.pdf')

example_dwp_pdf = file('tests/test_pdfs/example_dwp_pdf.pdf')

landscape_oriented_page = file('tests/test_pdfs/landscape_oriented_page.pdf')

landscape_rotated_page = file('tests/test_pdfs/landscape_rotated_page.pdf')

multi_page_pdf = file('tests/test_pdfs/multi_page_pdf.pdf')

no_colour = file('tests/test_pdfs/no_colour.pdf')

not_pdf = file(__file__)

one_page_pdf = file('tests/test_pdfs/one_page_pdf.pdf')

portrait_rotated_page = file('tests/test_pdfs/portrait_rotated_page.pdf')

repeated_address_block = file('tests/test_pdfs/repeated_address_block.pdf')

rgb_image_pdf = file('tests/test_pdfs/rgb_image.pdf')
