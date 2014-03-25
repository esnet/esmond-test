esnet-gh-pages-base
===================

Base templates for ESnet's GitHub pages. These pages are created using the
Sphinx_ documentation package using the _sphinx-boostrap-theme with some
pages.  This repo is meant to be included into a project using git subtree and
provides the overrides and customizations to the base theme.

.. _Sphinx: http://sphinx-doc.org
.. _sphinx-boostrap-theme: https://github.com/ryan-roemer/sphinx-bootstrap-theme

Getting Started
~~~~~~~~~~~~~~~

1. Install Sphinx and sphinx-bootstrap-theme. See the instructions below for
   installing these either using the Mac OS X base system python or MacPorts.
2. cd $PROJECT_ROOT
3. mkdir docs
4. git subtree add --prefix docs/_esnet \
   https://github.com/esnet/esnet-gh-pages-base.git master --squash
5. cd docs
6. sphinx-quickstart
7. edit in changes from _esnet/conf.py

Sphinx Installation using Mac OS X Base Python
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. sudo /usr/bin/easy_install pip
2. sudo /usr/local/bin/pip install sphinx sphinx-bootstrap-theme

Sphinx Installation using MacPorts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. port install python27 py27-pip py27-sphinx
2. port select pip py27-pip
3. port select sphinx py27-sphinx
4. pip install sphinx sphinx-bootstrap-theme # make sure this is
   /opt/local/bin/pip

Publishing
~~~~~~~~~~
