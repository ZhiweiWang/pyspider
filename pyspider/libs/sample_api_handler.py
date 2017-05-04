#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# Created on __DATE__
# Project: __PROJECT_NAME__

import re
from pyspider.libs.base_handler import BaseHandler
# catch_status_code_error, config, every
from pyspider.libs.utils_api import save_response, save_result
import requests


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
