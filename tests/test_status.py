import json

from flask import url_for


def test_status_returns_binary_versions(client):
    resp = client.get(url_for('status_blueprint._status'))

    assert resp.status_code == 200
    json_data = json.loads(resp.get_data(as_text=True))

    assert json_data['ghostscript_version'] is not None
    assert json_data['imagemagick_version'] is not None
