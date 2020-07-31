# The source pdfs are located here - https://github.com/alphagov/notifications-utils/tree/master/tests/testfiles


def file(filename):
    with open(filename, 'rb') as f:
        return f.read()


# valid
valid_letter = file('tests/test_pdfs/valid_letter.pdf')
blank_with_address = file('tests/test_pdfs/blank_with_address.pdf')

# invalid

# unable-to-read-file
not_pdf = file('tests/test_pdfs/invalid-svg-file.svg')


# letter-not-a4-portrait-oriented
a3_size = file('tests/test_pdfs/a3_size.pdf')
a5_size = file('tests/test_pdfs/a5_size.pdf')
# page is orientated in landscape
landscape_oriented_page = file('tests/test_pdfs/landscape_oriented_page.pdf')
# page is orientated portrait but rotated 90º
landscape_rotated_page = file('tests/test_pdfs/landscape_rotated_page.pdf')

# content-outside-printable-area
address_block_repeated_on_second_page = file('tests/test_pdfs/address_block_repeated_on_second_page.pdf')
address_margin = file('tests/test_pdfs/address_margin.pdf')
example_dwp_pdf = file('tests/test_pdfs/example_dwp_pdf.pdf')
no_colour = file('tests/test_pdfs/no_colour.pdf')
repeated_address_block = file('tests/test_pdfs/repeated_address_block.pdf')

# address-is-empty
multi_page_pdf = file('tests/test_pdfs/multi_page_pdf.pdf')
blank_page = file('tests/test_pdfs/blank_page.pdf')
# bad postcode
bad_postcode = file('tests/test_pdfs/bad_postcode.pdf')
# wrong number of address lines
blank_with_2_line_address = file('tests/test_pdfs/blank_with_2_line_address.pdf')
blank_with_8_line_address = file('tests/test_pdfs/blank_with_8_line_address.pdf')
# page is orientated landscape but rotated 90º - all the text is sideways but it's still portrait. OK
portrait_rotated_page = file('tests/test_pdfs/portrait_rotated_page.pdf')
# invalid char in address
invalid_address_character = file('tests/test_pdfs/invalid_address_character.pdf')

# we don't test validation for these files, just colour transformation
rgb_image_pdf = file('tests/test_pdfs/rgb_image.pdf')
cmyk_and_rgb_images_in_one_pdf = file('tests/test_pdfs/cmyk_and_rgb_in_one_pdf.pdf')
cmyk_image_pdf = file('tests/test_pdfs/cmyk_image.pdf')
