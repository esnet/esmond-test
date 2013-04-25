import os
import os.path
import sys
import site

try:
    ESMOND_GRAPHITE_ROOT = os.environ['ESMOND_GRAPHITE_ROOT']
except:
    ESMOND_GRAPHITE_ROOT = os.path.dirname(os.path.abspath(__file__)) + "/.."

sys.path.append(ESMOND_GRAPHITE_ROOT)
os.environ['DJANGO_SETTINGS_MODULE'] = 'esmond_graphite.settings'


# This assumes you have deployed Graphite in a virtual env
pyver = "%d.%d" % (sys.version_info[0], sys.version_info[1])
venv_dir = '%s/lib/python%s/site-packages' % (ESMOND_GRAPHITE_ROOT, pyver)
site.addsitedir(venv_dir)

import django.core.handlers.wsgi

application = django.core.handlers.wsgi.WSGIHandler()
