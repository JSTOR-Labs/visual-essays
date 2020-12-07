#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
logging.basicConfig(format='%(asctime)s : %(filename)s : %(levelname)s : %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

import os
import sys
import re
import json
import getopt
import base64
from urllib.parse import urlparse, unquote, urlencode

import requests
logging.getLogger('requests').setLevel(logging.INFO)

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
BASEDIR = os.path.dirname(SCRIPT_DIR)
while BASEDIR != '/' and not os.path.exists(os.path.join(BASEDIR, 'index.html')):
    BASEDIR = os.path.dirname(BASEDIR)
logger.info(f'SCRIPT_DIR={SCRIPT_DIR} BASEDIR={BASEDIR}')

from flask import Flask, request, send_from_directory, redirect, Response, jsonify, g
app = Flask(__name__, static_url_path='/static', static_folder=os.path.join(BASEDIR, 'static'))

from essay import get_essay
from gh import gh_token, get_gh_file, gh_repo_info, has_gh_repo_prefix

ENV = 'prod'
CONTENT_ROOT = None

KNOWN_SITES = {
    'default': ['jstor-labs', 've-docs'],
    'plant-humanities.app': ['jstor-labs', 'plant-humanities'],
    'kent-maps.online': ['kent-map', 'kent']
}

cors_headers = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Credentials': True,
    'Access-Control-Allow-Methods': 'PUT, PATCH, GET, POST, DELETE, OPTIONS, HEAD',
    'Access-Control-Allow-Headers': 'ETag, Vary, Accept, Authorization, Prefer, Content-type, Link, Allow, Content-location, Location',
    'Access-Control-Expose-Headers': 'ETag, Vary, Accept, Authorization, Prefer, Content-type, Link, Allow, Content-location, Location',
    'Allow': 'PUT, PATCH, GET, POST, DELETE, OPTIONS, HEAD'
}

def _is_local(site):
    return site.startswith('localhost') or site.endswith('gitpod.io')

def _is_ve_site(site):
    _site = site[4:] if site[:4] in ('dev.', 'exp.') else site
    return _site == 'visual-essays.app' or _is_local(site)

def qargs():
    return dict([(k, request.args.get(k)) for k in request.args])

def _normalize_path(path):
    return f'/{path[:-1] if path[-1] == "/" else path}' if path else '/'

def _context(path):
    path = _normalize_path(path)
    site = urlparse(request.base_url).hostname
    branch = qargs().get('ref', 'main')
    logger.info(f'_context: _is_ve_site={_is_ve_site(site)} gh_repo_prefix={has_gh_repo_prefix(path)}')
    if _is_ve_site(site) and has_gh_repo_prefix(path):
        acct, repo = path[1:].split('/')[:2]
    else:
        acct, repo = KNOWN_SITES.get(site, KNOWN_SITES['default'])
    return site, acct, repo, branch, path

@app.route('/config.json', methods=['GET'])
def local_config():
    logger.info(f'local_config: ENV={ENV} CONTENT_ROOT={CONTENT_ROOT}')
    if ENV == 'dev' and CONTENT_ROOT:
        config_path = os.path.join(CONTENT_ROOT, 'config.json')
        if os.path.exists(config_path):
            return json.load(open(config_path, 'r')), 200
    return 'Not found', 404

@app.route('/config/<path:path>', methods=['GET'])
@app.route('/config/', methods=['GET'])
@app.route('/config', methods=['GET'])
def config(path=None):
    site, acct, repo, branch, path = _context(path)
    logger.info(f'config: site={site} acct={acct} repo={repo} branch={branch} path={path}')
    raw, _ = get_gh_file( acct, repo, branch, '/config.json')
    _config = json.loads(raw) if raw is not None else {} 
    _config.update({'acct': acct, 'repo': repo, 'branch': branch})
    return _config, 200, cors_headers

@app.route('/essay/<path:path>', methods=['GET'])
@app.route('/essay/', methods=['GET'])
def essay(path=None):
    site, acct, repo, branch, path = _context(path)
    logger.info(f'essay: site={site} acct={acct} repo={repo} branch={branch} path={path}')
    essay_args = {'site': site, 'acct': acct, 'repo': repo, 'branch': branch, 'path': path, 'root': CONTENT_ROOT, 'token': gh_token()}
    essay_html = get_essay(**essay_args)
    if essay_html:
        return essay_html, 200, cors_headers
    return 'Not found', 404

@app.route('/components/<path:path>', methods=['GET'])
def assets(path):
    full_path = f'{BASEDIR}/components/{path}'
    logger.info(f'components: path={path} full_path={full_path} exists={os.path.exists(full_path)}')
    if os.path.exists(full_path):
        path_elems = full_path.split('/')
        return send_from_directory(f'/{"/".join(path_elems[:-1])}', path_elems[-1], as_attachment=False)
    else:
        return 'Not found', 404

@app.route('/info', methods=['GET'])
def info():
    return {'SCRIPT_DIR': SCRIPT_DIR, 'BASEDIR': BASEDIR}, 200

@app.route('/<path:path>', methods=['GET'])
@app.route('/', methods=['GET'])
def main(path=None):
    site, acct, repo, branch, path = _context(path)
    logger.info(f'main: site={site} acct={acct} repo={repo} branch={branch} path={path}')
    with open(os.path.join(BASEDIR, 'index.html'), 'r') as fp:
        html = fp.read()
        if ENV == 'dev':
            if site.endswith('gitpod.io'):
                html = re.sub(r'"/static/js/visual-essays.+"', f'"{os.environ.get("core_js_host")}/lib/visual-essays.js"', html)
            else:
                html = re.sub(r'"/static/js/visual-essays.+"', f'"http://{site}:8088/js/visual-essays.js"', html)
        return html, 200

    return 'Not found', 404

def usage():
    print('%s [hl:da:r:c:]' % sys.argv[0])
    print('   -h --help             Print help message')
    print('   -l --loglevel         Logging level (default=warning)')
    print('   -d --dev              Use local Visual Essay JS Lib')
    print('   -a --acct             Default Github account (jstor-labs)')
    print('   -r --repo             Default Github repository (ve-docs)')
    print('   -c --root             Content root')

if __name__ == '__main__':
    try:
        opts, args = getopt.getopt(sys.argv[1:], 'hl:da:r:c:', ['help', 'loglevel', 'dev', 'acct', 'repo', 'root'])
    except getopt.GetoptError as err:
        # print help information and exit:
        print(str(err)) # will print something like "option -a not recognized"
        usage()
        sys.exit(2)

    for o, a in opts:
        if o in ('-l', '--loglevel'):
            loglevel = a.lower()
            if loglevel in ('error',): logger.setLevel(logging.ERROR)
            elif loglevel in ('warn','warning'): logger.setLevel(logging.INFO)
            elif loglevel in ('info',): logger.setLevel(logging.INFO)
            elif loglevel in ('debug',): logger.setLevel(logging.DEBUG)
        elif o in ('-d', '--dev'):
            ENV = 'dev'
        elif o in ('-a', '--acct'):
            KNOWN_SITES['default'][0] = a
        elif o in ('-r', '--repo'):
            KNOWN_SITES['default'][1] = a
        elif o in ('-c', '--root'):
            CONTENT_ROOT = d
        elif o in ('-h', '--help'):
            usage()
            sys.exit()
        else:
            assert False, 'unhandled option'

    logger.info(f'ENV={ENV}')
    app.run(debug=True, host='0.0.0.0', port=8080)