#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# vim: set et sw=4 ts=4 sts=4 ff=unix fenc=utf8:
# Author: Binux<i@binux.me>
#         http://binux.me
# Created on 2014-02-23 00:19:06


import datetime
import hashlib
import inspect
import socket
import sys
import time
import traceback
from flask import json, jsonify, render_template, request

try:
    import flask_login as login
except ImportError:
    from flask.ext import login

from pyspider.libs import dataurl, sample_api_handler, sample_handler, utils
from pyspider.libs.response import rebuild_response
from pyspider.processor.project_module import ProjectFinder, ProjectManager
from .app import app

default_task = {
    'taskid': 'data:,on_start',
    'project': '',
    'url': 'data:,on_start',
    'process': {
        'callback': 'on_start',
    },
}
default_script = inspect.getsource(sample_handler)
default_api_script = inspect.getsource(sample_api_handler)


@app.route('/api/', methods=['POST'])
def api():
    app.logger.warning(str(request.form))
    project = request.form['project']
    url = request.form['url']
    parser = request.form.get('parser', 'page_parser')
    fetch_type = request.form.get('fetch_type', None)
    user_agent = request.form.get(
        'user_agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/57.0.2987.138 Safari/537.36')
    headers = request.form.get('headers', {})
    cookies = request.form.get('cookies', {})
    extra_save = request.form.get('extra_save', {})

    md5 = hashlib.md5()
    md5.update(json.dumps(cookies))
    md5.update(json.dumps(headers))
    md5.update(user_agent)
    md5.update(json.dumps(extra_save))

    projectdb = app.config['projectdb']
    if not projectdb.verify_project_name(project):
        ret = {
            'code': 400,
            'error': 'project name is not allowed!',
        }
        return jsonify(ret)
    # script = request.form['script']
    project_info = projectdb.get(project, fields=['name', 'status', 'group'])
    if project_info and 'lock' in projectdb.split_group(project_info.get('group')) \
            and not login.current_user.is_active():
        return app.login_response

    updated_project_info = False
    if project_info:
        app.logger.warning('get project', project_info)
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
    task = instance.crawl(url=url, callback=getattr(instance, parser),
                          user_agent=user_agent, retries=5, age=3,
                          headers=headers, cookies=cookies,
                          save=extra_save, itag=md5.hexdigest(),
                          fetch_type=fetch_type, validate_cert=False,
                          )
    task['status'] = 1
    app.logger.warning(str(task))

    # taskdb = app.config['taskdb']
    # task2 = taskdb.insert(project, task['taskid'], task)
    # # task2 = taskdb.get_task(project, task['taskid'])
    # print(task2)

    rpc = app.config['scheduler_rpc']
    if rpc is not None:
        try:
            rpc.newtask(task)
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


@app.route('/debug/<project>', methods=['GET', 'POST'])
def debug(project):
    projectdb = app.config['projectdb']
    if not projectdb.verify_project_name(project):
        return 'project name is not allowed!', 400
    info = projectdb.get(project, fields=['name', 'script'])
    if info:
        script = info['script']
    else:
        script = (default_script
                  .replace('__DATE__', datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                  .replace('__PROJECT_NAME__', project)
                  .replace('__START_URL__', request.values.get('start-urls') or '__START_URL__'))

    taskid = request.args.get('taskid')
    if taskid:
        taskdb = app.config['taskdb']
        task = taskdb.get_task(
            project, taskid, ['taskid', 'project', 'url', 'fetch', 'process'])
    else:
        task = default_task

    default_task['project'] = project
    return render_template("debug.html", task=task, script=script, project_name=project)


@app.before_first_request
def enable_projects_import():
    sys.meta_path.append(ProjectFinder(app.config['projectdb']))


@app.route('/debug/<project>/run', methods=['POST', ])
def run(project):
    start_time = time.time()
    try:
        task = utils.decode_unicode_obj(json.loads(request.form['task']))
    except Exception:
        result = {
            'fetch_result': "",
            'logs': u'task json error',
            'follows': [],
            'messages': [],
            'result': None,
            'time': time.time() - start_time,
        }
        return json.dumps(utils.unicode_obj(result)), \
            200, {'Content-Type': 'application/json'}

    project_info = {
        'name': project,
        'status': 'DEBUG',
        'script': request.form['script'],
    }

    if request.form.get('webdav_mode') == 'true':
        projectdb = app.config['projectdb']
        info = projectdb.get(project, fields=['name', 'script'])
        if not info:
            result = {
                'fetch_result': "",
                'logs': u' in wevdav mode, cannot load script',
                'follows': [],
                'messages': [],
                'result': None,
                'time': time.time() - start_time,
            }
            return json.dumps(utils.unicode_obj(result)), \
                200, {'Content-Type': 'application/json'}
        project_info['script'] = info['script']

    fetch_result = {}
    try:
        module = ProjectManager.build_module(project_info, {
            'debugger': True,
            'process_time_limit': app.config['process_time_limit'],
        })

        # The code below is to mock the behavior that crawl_config been joined when selected by scheduler.
        # but to have a better view of joined tasks, it has been done in BaseHandler.crawl when `is_debugger is True`
        # crawl_config = module['instance'].crawl_config
        # task = module['instance'].task_join_crawl_config(task, crawl_config)

        fetch_result = app.config['fetch'](task)
        response = rebuild_response(fetch_result)

        ret = module['instance'].run_task(module['module'], task, response)
    except Exception:
        type, value, tb = sys.exc_info()
        tb = utils.hide_me(tb, globals())
        logs = ''.join(traceback.format_exception(type, value, tb))
        result = {
            'fetch_result': fetch_result,
            'logs': logs,
            'follows': [],
            'messages': [],
            'result': None,
            'time': time.time() - start_time,
        }
    else:
        result = {
            'fetch_result': fetch_result,
            'logs': ret.logstr(),
            'follows': ret.follows,
            'messages': ret.messages,
            'result': ret.result,
            'time': time.time() - start_time,
        }
        result['fetch_result']['content'] = response.text
        if (response.headers.get('content-type', '').startswith('image')):
            result['fetch_result']['dataurl'] = dataurl.encode(
                response.content, response.headers['content-type'])

    try:
        # binary data can't encode to JSON, encode result as unicode obj
        # before send it to frontend
        return json.dumps(utils.unicode_obj(result)), 200, {'Content-Type': 'application/json'}
    except Exception:
        type, value, tb = sys.exc_info()
        tb = utils.hide_me(tb, globals())
        logs = ''.join(traceback.format_exception(type, value, tb))
        result = {
            'fetch_result': "",
            'logs': logs,
            'follows': [],
            'messages': [],
            'result': None,
            'time': time.time() - start_time,
        }
        return json.dumps(utils.unicode_obj(result)), 200, {'Content-Type': 'application/json'}


@app.route('/debug/<project>/save', methods=['POST', ])
def save(project):
    projectdb = app.config['projectdb']
    if not projectdb.verify_project_name(project):
        return 'project name is not allowed!', 400
    script = request.form['script']
    project_info = projectdb.get(project, fields=['name', 'status', 'group'])
    if project_info and 'lock' in projectdb.split_group(project_info.get('group')) \
            and not login.current_user.is_active():
        return app.login_response

    if project_info:
        info = {
            'script': script,
        }
        if project_info.get('status') in ('DEBUG', 'RUNNING', ):
            info['status'] = 'CHECKING'
        projectdb.update(project, info)
    else:
        info = {
            'name': project,
            'script': script,
            'status': 'TODO',
            'rate': app.config.get('max_rate', 1),
            'burst': app.config.get('max_burst', 3),
        }
        projectdb.insert(project, info)

    rpc = app.config['scheduler_rpc']
    if rpc is not None:
        try:
            rpc.update_project()
        except socket.error as e:
            app.logger.warning('connect to scheduler rpc error: %r', e)
            return 'rpc error', 200

    return 'ok', 200


@app.route('/debug/<project>/get')
def get_script(project):
    projectdb = app.config['projectdb']
    if not projectdb.verify_project_name(project):
        return 'project name is not allowed!', 400
    info = projectdb.get(project, fields=['name', 'script'])
    return json.dumps(utils.unicode_obj(info)), \
        200, {'Content-Type': 'application/json'}


@app.route('/blank.html')
def blank_html():
    return ""
