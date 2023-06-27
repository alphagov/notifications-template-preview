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
                "service": {"type": "string"},
                "subject": {"type": "string"},
                "content": {"type": "string"},
                "letter_attachment": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {"page_count": {"type": "integer"}},
                            "required": ["page_count"],
                        },
                        {"type": "null"},
                    ]
                },
            },
            "required": ["subject", "content"],
        },
        "filename": {"type": ["string", "null"]},
        "date": {"type": ["string", "null"]},
    },
    "required": ["letter_contact_block", "template", "values", "filename"],
    "additionalProperties": False,
}

letter_attachment_preview_schema = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "description": "schema for parameters allowed when generating a template preview",
    "type": "object",
    "properties": {
        "service_id": {"type": "string"},
        "letter_attachment_id": {"type": "string"},
    },
    "required": ["service_id", "letter_attachment_id"],
    "additionalProperties": False,
}
