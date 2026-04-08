#!/usr/bin/env python
# -*- coding: utf-8 -*-

__version__ = "1.0.1"
__short_description__ = "Multiple API Key Manager (Next Generation, sqlalchemy_mate free)"
__license__ = "MIT"
__author__ = "apipool-ng Contributors"
__author_email__ = ""
__maintainer__ = "apipool-ng Contributors"
__maintainer_email__ = ""
__github_username__ = ""

try:
    from .apikey import ApiKey
    from .manager import ApiKeyManager
    from .stats import StatusCollection
except Exception as e:  # pragma: no cover
    pass
