#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

import apipool as package

setup(
    name="apipool-ng",
    version=package.__version__,
    description=package.__short_description__,
    long_description=open("README.md", "rb").read().decode("utf-8"),
    long_description_content_type="text/markdown",
    author=package.__author__,
    author_email=package.__author_email__,
    maintainer=package.__maintainer__,
    maintainer_email=package.__maintainer_email__,
    license=package.__license__,
    packages=["apipool"] + ["apipool.%s" % i for i in find_packages("apipool")],
    include_package_data=True,
    url="https://github.com/apipool-ng/apipool-project",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: MacOS",
        "Operating System :: Unix",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ],
    python_requires=">=3.8",
    install_requires=[line.strip() for line in open("requirements.txt") if line.strip() and not line.startswith("#")],
)
