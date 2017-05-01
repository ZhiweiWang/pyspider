import base64
import functools
import json
import boto3


def save_response(func):
    @functools.wraps(func)
    def wrapper(self, response):
        content = response.content
        if response.encoding != 'unicode':
            content = content.decode(response.encoding)
        ret = {
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

        function = func.__get__(self, self.__class__)
        function(response)
        return ret
    return wrapper


def save_result(func):
    @functools.wraps(func)
    def wrapper(self, result):
        if not result:
            return
        print('------------------')
        print(result['orig_url'], result['status_code'], result['url'],
              result['title'], result['extra_save'], result['json'])
        content = result.pop('content')
        content_type = 'text/html'
        json_data = result.pop('json')
        if json_data:
            content = json.dumps(json_data)
            content_type = 'application/json'
        s3 = boto3.resource('s3')
        file = 'html/' + base64.urlsafe_b64encode(result['orig_url'])
        result['file'] = file
        res = s3.Object('nonda.spider', file).put(ACL='public-read', Body=content,
                                                  ContentType=content_type,)
        assert res['ResponseMetadata']['HTTPStatusCode'] == 200, str(res)

        function = func.__get__(self, self.__class__)
        ret = function(result)
        return ret
    return wrapper
