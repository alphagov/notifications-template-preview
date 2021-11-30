# Hitting the application manually

For authenticated endpoints, HTTP Token Authentication is used - by default, locally it's set to `my-secret-key`.

```shell
curl \
  -X POST \
  -H "Authorization: Token my-secret-key" \
  -H "Content-type: application/json" \
  -d '{
    "template":{
      "subject": "foo",
      "content": "bar",
      "template_type": "letter"
    },
    "values": null,
    "letter_contact_block": "baz",
    "filename": "hm-government"
  }' \
  http://localhost:6013/preview.pdf
```

- `template` is an object containing the subject and content of the letter, including any placeholders
- `values` is an object containing the keys and values which should be used to populate the placeholders and the lines of the address
- `letter_contact_block` is the text that appears in the top right of the first page, can include placeholders
- `filename` is an absolute URL of the logo that goes in the top left of the first page (must be an SVG image)

