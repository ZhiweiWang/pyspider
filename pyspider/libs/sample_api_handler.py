#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# Created on __DATE__
# Project: __PROJECT_NAME__

from pyspider.libs.base_handler import BaseHandler
from pyspider.libs.utils_api import save_response, save_result
# catch_status_code_error, config, every


class Handler(BaseHandler):
    crawl_config = {
    }

    def on_start(self):
        return

    @save_response
    def page_parser(self, response):
        pass

    @save_result
    def on_result(self, result):
        super(Handler, self).on_result(result)
