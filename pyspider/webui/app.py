#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# vim: set et sw=4 ts=4 sts=4 ff=unix fenc=utf8:
# Author: Binux<i@binux.me>
#         http://binux.me
# Created on 2014-02-22 23:17:13

import logging
import os
import sys
from apscheduler.schedulers.tornado import TornadoScheduler
from flask import Flask
from pyspider.fetcher import tornado_fetcher
from six import reraise
from six.moves import builtins
from six.moves.urllib.parse import urljoin
# from .job import check_failed

logger = logging.getLogger("webui")

if os.name == 'nt':
    import mimetypes
    mimetypes.add_type("text/css", ".css", True)


def check_failed():
    import json
    import logging
    import time
    from itertools import chain
    import requests
    from .app import app
    # from pyspider.processor.project_module import ProjectManager

    projectdb = app.config['projectdb']
    # project_manager = ProjectManager(projectdb, {})
    taskdb = app.config['taskdb']
    resultdb = app.config['resultdb']

    now = time.time()

    projects = projectdb.get_all(fields=['name', 'status', 'group'])
    for project_info in projects:
        if project_info['status'] in ['TODO', 'STOP']:
            continue
        logger.info(json.dumps(project_info))
        project = project_info['name']
        # module = project_manager.get(project)
        # instance = module['instance']
        # if not hasattr(instance, 'failed_callback'):
        #     logger.info(json.dumps(instance))
        #     continue

        fail_tasks = taskdb.load_tasks(3, project)
        done_tasks = taskdb.load_tasks(2, project)
        tasks = chain(fail_tasks, done_tasks)
        for task in tasks:
            # logger.info(' '.join(('failed', task['url'], str(task['callback_success']))))
            if task['callback_success'] == 1:
                # logger.info('cancel callback for success')
                continue
            if task.get('callback_time_next', 0) > now:
                # logger.info('delayed callback')
                continue
            if task['callback_url'] is None:
                task['callback_success'] = 1
                taskdb.update(project, task['taskid'], task)
                return
            # logger.info(json.dumps(task))
            flag_failed = False
            pre_time = task.get('callback_time', 0)
            task['callback_time'] = now
            result = resultdb.get(task['project'], task['taskid'])
            # logger.info(json.dumps(result))
            ret = {"url": task['url']}
            if task['status'] == 2:
                ret['meta'] = 'success'
                ret['data'] = result['result']['ret'] if 'ret' in result['result'] else result['result']
            else:
                ret['meta'] = 'failed'
                ret['data'] = task
            callback_url = task['callback_url']
            # logger.info('send callback to %s with json %s' % (callback_url, json.dumps(ret)))
            try:
                r = requests.post(callback_url, json=ret, timeout=5)
                if r.status_code != requests.codes.ok:
                    flag_failed = True
            except Exception:
                flag_failed = True
            finally:
                if flag_failed:
                    logger.info('callback failed from %s' % callback_url)
                    task['callback_success'] = 0
                    if task.get('callback_time_next', 0) > 0:
                        task['callback_time_next'] = now + min(
                            3600,
                            task['callback_time_next'] - pre_time) * 2
                    else:
                        task['callback_time_next'] = now + 1
                else:
                    logger.info('callback success from %s' % callback_url)
                    task['callback_success'] = 1
                taskdb.update(project, task['taskid'], task)


class QuitableFlask(Flask):
    """Add quit() method to Flask object"""
    redis_con = None

    @property
    def logger(self):
        return logger

    def run(self, host=None, port=None, debug=None, **options):
        import tornado.wsgi
        import tornado.ioloop
        import tornado.httpserver
        import tornado.web

        if host is None:
            host = '127.0.0.1'
        if port is None:
            server_name = self.config['SERVER_NAME']
            if server_name and ':' in server_name:
                port = int(server_name.rsplit(':', 1)[1])
            else:
                port = 5000
        if debug is not None:
            self.debug = bool(debug)

        hostname = host
        port = port
        application = self
        use_reloader = self.debug
        use_debugger = self.debug

        if use_debugger:
            from werkzeug.debug import DebuggedApplication
            application = DebuggedApplication(application, True)

        try:
            from .webdav import dav_app
        except ImportError as e:
            logger.warning('WebDav interface not enabled: %r', e)
            dav_app = None
        if dav_app:
            from werkzeug.wsgi import DispatcherMiddleware
            application = DispatcherMiddleware(application, {
                '/dav': dav_app
            })

        container = tornado.wsgi.WSGIContainer(application)
        self.http_server = tornado.httpserver.HTTPServer(container)
        self.http_server.listen(port, hostname)
        if use_reloader:
            from tornado import autoreload
            autoreload.start()

        self.logger.info('webui running on %s:%s', hostname, port)
        self.ioloop = tornado.ioloop.IOLoop.current()
        self.ioloop.start()

    def quit(self):
        if hasattr(self, 'ioloop'):
            self.ioloop.add_callback(self.http_server.stop)
            self.ioloop.add_callback(self.ioloop.stop)
        self.logger.info('webui exiting...')


app = QuitableFlask('webui',
                    static_folder=os.path.join(os.path.dirname(__file__), 'static'),
                    template_folder=os.path.join(os.path.dirname(__file__), 'templates'))
app.secret_key = os.urandom(24)
app.jinja_env.line_statement_prefix = '#'
app.jinja_env.globals.update(builtins.__dict__)

app.config.update({
    'fetch': lambda x: tornado_fetcher.Fetcher(None, None, async=False).fetch(x),
    'taskdb': None,
    'projectdb': None,
    'scheduler_rpc': None,
    'queues': dict(),
    'process_time_limit': 30,
})

apsched = TornadoScheduler()
apsched.add_job(check_failed, 'interval', seconds=10)
apsched.start()


def cdn_url_handler(error, endpoint, kwargs):
    if endpoint == 'cdn':
        path = kwargs.pop('path')
        # cdn = app.config.get('cdn', 'http://cdn.staticfile.org/')
        # cdn = app.config.get('cdn', '//cdnjs.cloudflare.com/ajax/libs/')
        cdn = app.config.get('cdn', '//cdnjscn.b0.upaiyun.com/libs/')
        return urljoin(cdn, path)
    else:
        exc_type, exc_value, tb = sys.exc_info()
        if exc_value is error:
            reraise(exc_type, exc_value, tb)
        else:
            raise error
app.handle_url_build_error = cdn_url_handler
