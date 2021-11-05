# The source pdfs are located here - https://github.com/alphagov/notifications-utils/tree/master/tests/testfiles
# If you wish to add a new source file then you will also need to add it to the .gitignore file


def file(filename):
    with open(filename, 'rb') as f:
        return f.read()


# valid
valid_letter = file('tests/test_pdfs/valid_letter.pdf')
blank_with_address = file('tests/test_pdfs/blank_with_address.pdf')
already_has_notify_tag = file('tests/test_pdfs/already_has_notify_tag.pdf')

# all writeable areas filled
all_areas_filled = file('tests/test_pdfs/all_areas_filled.pdf')

# unable-to-read-file
not_pdf = file('tests/test_pdfs/invalid-svg-file.svg')

# no metadata for logging
pdf_with_no_metadata = file('tests/test_pdfs/pdf_with_no_metadata.pdf')

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

# notify-tag-found-in-content
notify_tags_on_page_2_and_4 = file('tests/test_pdfs/notify_tags_on_page_2_and_4.pdf')

# address-is-empty
multi_page_pdf = file('tests/test_pdfs/multi_page_pdf.pdf')
blank_page = file('tests/test_pdfs/blank_page.pdf')
# bad postcode
bad_postcode = file('tests/test_pdfs/bad_postcode.pdf')
# non-UK address
non_uk_address = file('tests/test_pdfs/non_uk_address.pdf')
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
rgb_black_pdf = file('tests/test_pdfs/rgb_black.pdf')

# pages for testing merging
single_sample_page = file('tests/test_pdfs/single_sample_page.pdf')
sample_pages = file('tests/test_pdfs/sample_pages.pdf')

# sample where logo was being stripped
public_guardian_sample = file('tests/test_pdfs/public_guardian_sample.pdf')
