from flask import abort


def test_bad_request(app, client):
    @app.route('/bad-request')
    def bad_request():
        abort(400, 'test error')

    response = client.get('/bad-request')
    assert response.status_code == 400

    assert response.json == {
        'message': '400 Bad Request: test error',
        'result': 'error'
    }
