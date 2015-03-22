from __future__ import unicode_literals

import re
from setuptools import setup, find_packages


def get_version(filename):
    content = open(filename).read()
    metadata = dict(re.findall("__([a-z]+)__ = '([^']+)'", content))
    return metadata['version']


setup(
    name='Mopidy-Youtube',
    version=get_version('mopidy_youtube/__init__.py'),
    url='https://github.com/dz0ny/mopidy-youtube',
    license='Apache License, Version 2.0',
    author='Janez Troha',
    author_email='dz0ny@ubuntu.si',
    description='Mopidy extension that plays sound from Youtube',
    long_description=open('README.rst').read(),
    packages=find_packages(exclude=['tests', 'tests.*']),
    zip_safe=False,
    include_package_data=True,
    install_requires=[
        'setuptools',
        'requests >= 2.2.1',
        'pafy >= 0.3.35',
        'Mopidy >= 1.0',
        'Pykka >= 1.1',
    ],
    test_suite='nose.collector',
    tests_require=[
        'nose',
        'mock >= 1.0',
        'vcrpy',
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
        'Topic :: Multimedia :: Sound/Audio :: Players',
    ],
)
