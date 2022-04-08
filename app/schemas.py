import jsonschema
from flask import abort


def get_and_validate_json_from_request(request, schema):
    json = request.get_json()
    try:
        jsonschema.validate(json, schema)
    except jsonschema.ValidationError as exc:
        abort(400, exc)
    return json


preview_schema = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "description": "schema for parameters allowed when generating a template preview",
    "type": "object",
    "properties": {
        "letter_contact_block": {"type": ["string", "null"]},
        "values": {"type": ["object", "null"]},
        "template": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["subject", "content"]
        },
        "filename": {"type": ["string", "null"]},
        "date": {"type": ["string", "null"]},
    },
    "required": ["letter_contact_block", "template", "values", "filename"],
    "additionalProperties": False,
}
