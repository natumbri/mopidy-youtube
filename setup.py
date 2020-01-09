from __future__ import unicode_literals

import re

from setuptools import find_packages, setup


def get_version(filename):
    content = open(filename).read()
    metadata = dict(re.findall("__([a-z]+)__ = '([^']+)'", content))
    return metadata['version']


setup(
    name='Mopidy-Youtube',  # Casing as originally registrered on PyPI
    version=get_version('mopidy_youtube/__init__.py'),
    url='https://github.com/natumbri/mopidy-youtube',
    license='Apache License, Version 2.0',
    author='Nik Tumbri',
    author_email='natumbri@gmail.com',
    description='Mopidy extension that plays sound from YouTube',
    long_description=open('README.rst').read(),
    packages=find_packages(exclude=['tests', 'tests.*']),
    zip_safe=False,
    include_package_data=True,
    install_requires=[
        'setuptools',
        'requests >= 2.2.1',
        'Mopidy >= 2.0',
        'Pykka >= 2.0.1',
        'youtube_dl',
        'bs4',
        'cachetools'
    ],
    entry_points={
        'mopidy.ext': [
            'youtube = mopidy_youtube:Extension',
        ],
    },
    classifiers=[
        'Environment :: No Input/Output (Daemon)',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2',
        'Development Status :: 3 - Alpha',
        'Topic :: Multimedia :: Sound/Audio :: Players',
    ],
)
