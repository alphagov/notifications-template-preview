from unittest.mock import Mock

import pytest

from app.pdf_redactor import get_encoding


@pytest.mark.parametrize(['font', 'encoding'], [
    (Mock(Encoding='SomeFont'), 'SomeFont'),
    (Mock(Encoding=Mock(BaseEncoding='SomeFont')), 'SomeFont'),
    (Mock(Encoding=Mock(spec=[])), None),
])
def test_get_encoding(font, encoding):
    assert get_encoding(font) == encoding
