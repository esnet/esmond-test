#!/usr/bin/env python

from distutils.core import setup

setup(name='esmond',
        version='0.9b1',
        description='ESnet Monitoring Daemon',
        author='Jon M. Dugan',
        author_email='jdugan@es.net',
        url='http://code.google.com/p/esmond/',
        packages=['esmond', 'esmond.api', 'esmond.api.client', 'esmond.admin'],
        install_requires=['tsdb', 'Django==1.5.1', 'django-tastypie', 'web.py',
            'python-memcached', 'pycassa', 'psycopg2','python-mimeparse',
            'requests', 'mock'],
        entry_points = {
            'console_scripts': [
                'espolld = esmond.poll:espolld',
                'espoll = esmond.poll:espoll',
                'espersistd = esmond.persist:espersistd',
                'esfetch = esmond.fetch:esfetch',
                'esdbd = esmond.newdb:esdb_standalone',
                'gen_ma_storefile = esmond.perfsonar:gen_ma_storefile',
                'esmanage = esmond.manage:esmanage',
            ]
        }
    )
