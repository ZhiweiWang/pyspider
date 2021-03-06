import base64
import functools
import json
# import boto3


def save_response(func):
    @functools.wraps(func)
    def wrapper(self, response):
        content = response.content
        if response.encoding != 'unicode':
            content = content.decode(response.encoding)
        result = {
            "url": response.url,
            "orig_url": response.orig_url,
            "status_code": str(response.status_code),
            "title": response.doc('title').text(),
            "headers": json.dumps(dict(response.headers)),
            "cookies": json.dumps(response.cookies),
            "content": content,
            "json": response.json,
            "extra_save": json.dumps(response.save or {}),
        }
        print('@save_response')
        print(result['orig_url'], result['status_code'], result['url'],
              result['title'], result['extra_save'])

        function = func.__get__(self, self.__class__)
        ret = function(response)
        result['ret'] = ret
        return result
    return wrapper


def save_result(func):
    @functools.wraps(func)
    def wrapper(self, result):
        print('@save_result')
        if not result:
            print('no result')
            return
        # print(result['orig_url'], result['status_code'], result['url'],
        #       result['title'], result['extra_save'])

        content = result.pop('content')
        content_type = 'text/html'
        json_data = result.pop('json')
        if json_data:
            content = json.dumps(json_data)
            content_type = 'application/json'
        file = 'html/' + base64.urlsafe_b64encode(result['orig_url'])
        result['file'] = file

        function = func.__get__(self, self.__class__)
        ret = function(result)
        # s3 = boto3.resource('s3')
        # s3.Object('nonda.spider', file).put(ACL='public-read', Body=content,
        #                                     ContentType=content_type,)
        # assert res['ResponseMetadata']['HTTPStatusCode'] == 200, str(res)
        return ret
    return wrapper
