#!/bin/bash
export WORKON_HOME=$HOME/.virtualenvs
export VIRTUALENVWRAPPER_PYTHON=/usr/bin/python2.7
source /usr/local/bin/virtualenvwrapper.sh
workon thetubes
cdvirtualenv SyncSend
python2.7 syncsend.py --pidfile /var/run/syncsend.pid 8000
