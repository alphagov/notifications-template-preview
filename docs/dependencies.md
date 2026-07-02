# Summary of PDF dependencies

The table below shows some of the main elements of creating letters, and which dependencies are involved in each.

|  | Final PDF for<br> precompiled letters | Final PDF for<br>templated letters | Notify tag | Address block | Validating content<br>is in printable area | Embedding fonts | Colours (RGB / CMYK) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| pdf2image <br> (and poppler) |  |  |  |  | ✅  |  |  |
| PyMuPDF | ✅ |  | ✅ | ✅ |  |  | ✅ |
| pypdf | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |  |
| reportlab | ✅ |  | ✅ | ✅ | ✅ |  |  |
| wand <br> (and imagemagick) |  |  |  |  |  |  |  |
| WeasyPrint |  | ✅ |  |  |  |  |  |
| ghostscript | ✅ | ✅ |  |  |  | ✅ | ✅ |

## Python dependencies
### pdf2image
- Along with `reportlab`, validates that precompiled letters don't contain content in the out of bounds areas
- Uses the `poppler` Docker dependency to work

### PyMuPDF
- Checks if precompiled letters contain RGB and CMYK colours
- Determines the boundary boxes for the Notify tag and address block
- Checks if a precompiled letter already contains a Notify tag on the first page (to see if we need to add one)
- Checks for the Notify tag on subsequent pages (this would make a letter invalid)
- Extracts the address text from the address block area
- Redacts the address

### pypdf
- Checks for unembedded fonts
- Gets the page count of PDFs
- Extracts a single page from a multi-page PDF
- Stitches PDFs or PDF pages together
- Raises an error if a PDF can't be read
- Converts between PDFs and bytes

### reportlab
- Contains various constants to do with colours and measurements
- Writes the address block and the Notify tag for precompiled letters
- Along with `pdf2image`, validates that precompiled letters don't contain content in the out of bounds areas

### wand
- An `imagemagick` binding for Python (`imagemagick` is a Docker dependency)
- Used for previewing letters only
- Covers the Notify tag with a white box so it doesn't appear when previewing a letter
- Generates the PNGs from a PDF

### WeasyPrint
- Creates the final PDF for a templated letter
- Used to preview templated letters

## Docker dependencies
### ghostscript
- Embeds fonts
- Converts colours to CMYK

### imagemagick
- See `wand` Python dependency

### poppler-utils
- See `pdf2image` Python dependency
