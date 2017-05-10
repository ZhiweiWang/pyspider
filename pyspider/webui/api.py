import datetime
import hashlib
import inspect
import socket
import sys
import time
import traceback
from urlparse import urlparse
from flask import json, jsonify, render_template, request

try:
    import flask_login as login
except ImportError:
    from flask.ext import login

from pyspider.libs import dataurl, sample_api_handler, sample_handler, utils
from pyspider.libs.response import rebuild_response
from pyspider.processor.project_module import ProjectFinder, ProjectManager
import redis
from .app import app

default_api_script = inspect.getsource(sample_api_handler)


def uri_validator(url):
    try:
        result = urlparse(url)
        return True if [result.scheme, result.netloc, result.path] else False
    except:
        return False


@app.route('/api/', methods=['POST'])
def api():
    json_data = request.get_json()
    # app.logger.error(str(json_data))
    project = json_data.pop('project')
    url = json_data.pop('url')
    if uri_validator(url) is False:
        ret = {
            'code': 403,
            'error': 'invalid url',
        }
        return jsonify(ret)
    callback_url = json_data.get('callback_url', '')
    if uri_validator(callback_url) is False:
        ret = {
            'code': 403,
            'error': 'invalid callback_url',
        }
        return jsonify(ret)
    parser = json_data.pop('parser', 'page_parser')
    if 'user_agent' not in json_data:
        json_data[
            'user_agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/57.0.2987.138 Safari/537.36'

    if app.redis_con is None:
        # newtask_queue = app.config['queues']['newtask_queue']
        # redis_kwargs = newtask_queue.redis.connection_pool.connection_kwargs.copy()
        # redis_kwargs['db'] = 3
        app.redis_con = redis.Redis(host="172.31.4.74", db=3)
    retries = json_data.pop('retries', 3)
    json_data['retries'] = retries
    proxies = []
    ban = set(app.redis_con.keys('*:*'))
    while len(proxies) == 0:
        proxies = app.redis_con.srandmember('proxy', retries * 3)
        proxies = [proxy.decode('utf8') for proxy in proxies if proxy not in ban]
    json_data['proxy'] = ','.join(proxies)
    # app.logger.info(json_data['proxy'])

    # md5 = hashlib.md5()
    # md5.update(json.dumps(json_data))

    projectdb = app.config['projectdb']
    if not projectdb.verify_project_name(project):
        ret = {
            'code': 400,
            'error': 'project name is not allowed!',
        }
        return jsonify(ret)
    # script = request.form['script']
    project_info = projectdb.get(project, fields=['name', 'status', 'group'])
    # if project_info and 'lock' in projectdb.split_group(project_info.get('group')) \
    #         and not login.current_user.is_active():
    #     return app.login_response

    updated_project_info = False
    if project_info:
        # app.logger.warning('get project', project_info)
        if project_info['status'] != 'RUNNING':
            info = {
                # 'script': script,
                'status': 'RUNNING',
            }
            projectdb.update(project, info)
            updated_project_info = True
    else:
        script = (default_api_script
                  .replace('__DATE__', datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                  .replace('__PROJECT_NAME__', project)
                  .replace('__START_URL__', url or '__START_URL__'))
        info = {
            'name': project,
            'script': script,
            'status': 'RUNNING',
            'rate': app.config.get('max_rate', 1),
            'burst': app.config.get('max_burst', 3),
        }
        projectdb.insert(project, info)
        updated_project_info = True

    if updated_project_info:
        rpc = app.config['scheduler_rpc']
        if rpc is not None:
            try:
                rpc.update_project()
            except socket.error as e:
                app.logger.warning('connect to scheduler rpc error: %r', e)
                ret = {
                    'code': 400,
                    'error': 'rpc error',
                }
                return jsonify(ret)

    project_manager = ProjectManager(projectdb, {})
    module = project_manager.get(project)

    instance = module['instance']
    if not hasattr(instance, parser):
        ret = {
            'code': 404,
            'error': 'request with wrong parser: %s' % parser,
        }
        return jsonify(ret)
    instance._reset()
    json_data['callback'] = getattr(instance, parser)
    task = instance.crawl(url, **json_data)
    # task['status'] = 1
    # app.logger.info(json.dumps(task))

    force_update = json_data.pop('force_update', False)
    taskdb = app.config['taskdb']
    expire = int(json_data.pop('expire', 24 * 60 * 60))
    json_data['expire'] = expire
    old_task = taskdb.get_task(project, task['taskid'])
    if old_task:
        resultdb = app.config['resultdb']
        result = resultdb.get(old_task['project'], old_task['taskid'])
        if force_update is False and result['updatetime'] + expire > time.time():
            task['status'] = 2
        task['callback_success'] = 0
        taskdb.update(project, task['taskid'], task)
    else:
        #     taskdb.insert(project, task['taskid'], task)

        # print(app.config)
        # app.config['newtask_queue'].put(task)
        rpc = app.config['scheduler_rpc']
        if rpc is not None:
            try:
                added = rpc.on_request(task)
                # added = rpc.send_task(task)
                # added = rpc.newtask(task)
                app.logger.info(' '.join(('add task', task['taskid'], str(added))))
            except socket.error as e:
                app.logger.warning('connect to scheduler rpc error: %r', e)
                ret = {
                    'code': 400,
                    'error': 'rpc error',
                }
                return jsonify(ret)

    ret = {
        'code': 200
    }
    return jsonify(ret)
