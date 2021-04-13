import uuid

import pytest
from flask import g
from freezegun import freeze_time

from app import notify_celery


# requiring app ensures notify_celery.init_app has been called
@pytest.fixture(scope='session')
def celery_task(app):
    @notify_celery.task(name=uuid.uuid4(), base=notify_celery.task_cls)
    def test_task(delivery_info=None):
        pass

    return test_task


@pytest.fixture
def async_task(celery_task):
    celery_task.push_request(delivery_info={'routing_key': 'test-queue'})
    yield celery_task
    celery_task.pop_request()


def test_success_should_log_and_call_statsd(mocker, app, async_task):
    statsd = mocker.patch.object(app.statsd_client, 'timing')
    logger = mocker.patch.object(app.logger, 'info')

    with freeze_time() as frozen:
        async_task()
        frozen.tick(5)

        async_task.on_success(
            retval=None, task_id=1234, args=[], kwargs={}
        )

    statsd.assert_called_once_with(f'celery.test-queue.{async_task.name}.success', 5.0)
    logger.assert_called_once_with(f'Celery task {async_task.name} (queue: test-queue) took 5.0000')


def test_success_queue_when_applied_synchronously(mocker, app, celery_task):
    statsd = mocker.patch.object(app.statsd_client, 'timing')
    logger = mocker.patch.object(app.logger, 'info')

    with freeze_time() as frozen:
        celery_task()
        frozen.tick(5)

        celery_task.on_success(
            retval=None, task_id=1234, args=[], kwargs={}
        )

    statsd.assert_called_once_with(f'celery.none.{celery_task.name}.success', 5.0)
    logger.assert_called_once_with(f'Celery task {celery_task.name} (queue: none) took 5.0000')


def test_failure_should_log_and_call_statsd(mocker, app, async_task):
    statsd = mocker.patch.object(app.statsd_client, 'incr')
    logger = mocker.patch.object(app.logger, 'exception')

    async_task.on_failure(
        exc=Exception, task_id=1234, args=[], kwargs={}, einfo=None
    )

    statsd.assert_called_once_with(f'celery.test-queue.{async_task.name}.failure')
    logger.assert_called_once_with(f'Celery task {async_task.name} (queue: test-queue) failed')


def test_failure_queue_when_applied_synchronously(mocker, app, celery_task):
    statsd = mocker.patch.object(app.statsd_client, 'incr')
    logger = mocker.patch.object(app.logger, 'exception')

    celery_task.on_failure(
        exc=Exception, task_id=1234, args=[], kwargs={}, einfo=None
    )

    statsd.assert_called_once_with(f'celery.none.{celery_task.name}.failure')
    logger.assert_called_once_with(f'Celery task {celery_task.name} (queue: none) failed')


def test_call_exports_request_id_from_kwargs(mocker, celery_task):
    g = mocker.patch('app.celery.celery.g')
    # this would fail if the kwarg was passed through unexpectedly
    celery_task(request_id='1234')
    assert g.request_id == '1234'


def test_apply_async_injects_global_request_id_into_kwargs(mocker, app, celery_task):
    super_apply = mocker.patch('celery.app.task.Task.apply_async')

    with app.app_context():
        g.request_id = '1234'
        celery_task.apply_async()

    super_apply.assert_called_with(None, {'request_id': '1234'})


def test_apply_async_inject_request_id_with_other_kwargs(mocker, app, celery_task):
    super_apply = mocker.patch('celery.app.task.Task.apply_async')

    with app.app_context():
        g.request_id = '1234'
        celery_task.apply_async(kwargs={'something': 'else'})

    super_apply.assert_called_with(None, {'request_id': '1234', 'something': 'else'})


def test_apply_async_inject_request_id_with_positional_args(mocker, app, celery_task):
    super_apply = mocker.patch('celery.app.task.Task.apply_async')

    with app.app_context():
        g.request_id = '1234'
        celery_task.apply_async(['args'], {'something': 'else'})

    super_apply.assert_called_with(['args'], {'request_id': '1234', 'something': 'else'})


def test_apply_async_injects_id_into_kwargs_from_request(mocker, app, celery_task):
    super_apply = mocker.patch('celery.app.task.Task.apply_async')
    request_id_header = app.config['NOTIFY_TRACE_ID_HEADER']
    request_headers = {request_id_header: '1234'}

    with app.test_request_context(headers=request_headers):
        celery_task.apply_async()

    super_apply.assert_called_with(None, {'request_id': '1234'})


def test_send_task_injects_global_request_id_into_kwargs(mocker, app):
    super_apply = mocker.patch('celery.Celery.send_task')

    with app.app_context():
        g.request_id = '1234'
        notify_celery.send_task('some-task')

    super_apply.assert_called_with('some-task', None, {'request_id': '1234'})


def test_send_task_injects_request_id_with_other_kwargs(mocker, app):
    super_apply = mocker.patch('celery.Celery.send_task')

    with app.app_context():
        g.request_id = '1234'
        notify_celery.send_task('some-task', kwargs={'something': 'else'})

    super_apply.assert_called_with('some-task', None, {'request_id': '1234', 'something': 'else'})


def test_send_task_injects_request_id_with_positional_args(mocker, app):
    super_apply = mocker.patch('celery.Celery.send_task')

    with app.app_context():
        g.request_id = '1234'
        notify_celery.send_task('some-task', ['args'], {'kw': 'args'})

    super_apply.assert_called_with('some-task', ['args'], {'request_id': '1234', 'kw': 'args'})


def test_send_task_injects_id_into_kwargs_from_request(mocker, app):
    super_apply = mocker.patch('celery.Celery.send_task')
    request_id_header = app.config['NOTIFY_TRACE_ID_HEADER']
    request_headers = {request_id_header: '1234'}

    with app.test_request_context(headers=request_headers):
        notify_celery.send_task('some-task')

    super_apply.assert_called_with('some-task', None, {'request_id': '1234'})
