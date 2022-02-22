# Visual testing

You should check a few sample PDFs look "OK" after any major changes to the way they are generated or previewed (as PNGs).

It can be helpful to open the before / after PDFs in a web browser, so you can quickly tab back and forth between them and spot any minor changes in doing so.

[Remember to run `make bootstrap-with-docker`](https://github.com/alphagov/notifications-template-preview#docker-container) if switching between versions of dependencies. If you don't, the code will run with an out-of-date image, using old / random dependencies.

## Method 1: Upload via Admin

This is easy: just run the apps locally and try to send letters before / after the change.

It doesn't matter if the validations pass or fail here: [the preview is the same either way](https://github.com/alphagov/notifications-admin/blob/5e8d0623de85eb0b10572635cdfc15ff6f35db32/app/templates/views/uploads/preview.html#L48).

WARNING: the preview you see is an image, [which may be subtly different to the actual PDF](https://github.com/alphagov/notifications-template-preview/pull/591#issuecomment-979284671). To avoid this, you can also pretend to send the PDF and download it using the link on the success page.

## Method 2: Forced generation

Some of the processing is conditional e.g. CMYK conversion, font embedding. You should consider [tweaking the code](https://github.com/alphagov/notifications-template-preview/commit/41f6e4605c405c37d64aa4a3160f604f948f8536) so you can force any PDF through the full gamut of processing we may do to it.

```bash
# reproduce changes without making a commit
git cherry-pick -n 41f6e4605c405c37d64aa4a3160f604f948f8536
```

Example command to test a PDF:

```python
# run in a flask shell
from app.precompiled import sanitise_file_contents
import base64

def convert(name, prefix):
  out = sanitise_file_contents(open(f'tests/test_pdfs/{name}.pdf', 'rb').read(), allow_international_letters=True, filename='foo')
  open(f'{prefix}_{name}.pdf', 'wb').write(base64.b64decode(out['file'].encode('utf-8')))
```

Suggested PDFs to test with:

```python
names = [
  'no_colour',
  'example_dwp_pdf',
  'public_guardian_sample',
  'address_block_repeated_on_second_page',
  'landscape_rotated_page',
  'hackney_sample'
]

# similarly for 'after' your change
for name in names: convert(name, 'before')
```

