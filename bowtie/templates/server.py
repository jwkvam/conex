#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import traceback
from functools import wraps

from builtins import bytes
import click
import msgpack
from flask import Flask, render_template, copy_current_request_context
from flask import request, Response
from flask_socketio import SocketIO, emit
import eventlet


class GetterNotDefined(AttributeError):
    pass


def check_auth(username, password):
    """This function is called to check if a username /
    password combination is valid.
    """
    return username == '{{ username }}' and password == '{{ password }}'

def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
    'Could not verify your access level for that URL.\n'
    'You have to login with proper credentials', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


# import the user created module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import {{source_module}}

app = Flask(__name__)
app.debug = {{ debug|default(False) }}
socketio = SocketIO(app, binary=True)
# not sure if this is secure or how much it matters
app.secret_key = os.urandom(256)

def context(func):
    def foo():
        with app.app_context():
            func()
    return foo


class Scheduler(object):

    def __init__(self, seconds, func):
        self.seconds = seconds
        self.func = func
        self.thread = None

    def start(self):
        self.thread = eventlet.spawn(self.run)

    def run(self):
        ret = eventlet.spawn(context(self.func))
        eventlet.sleep(self.seconds)
        try:
            ret.wait()
        except:
            traceback.print_exc()
        self.thread = eventlet.spawn(self.run)

    def stop(self):
        if self.thread:
            self.thread.cancel()


@app.route('/')
{% if basic_auth %}
@requires_auth
{% endif %}
def index():
    return render_template('index.html')


{% if login %}
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        success = {{ source_module }}.{{ login }}()
        if success:
            return redirect(url_for('index'))
        else:
            return redirect(url_for('login'))
    return {{ loginpage }}
{% endif %}


{% if initial %}
@socketio.on('INITIALIZE')
def _():
    foo = copy_current_request_context({{ source_module }}.{{ initial }})
    eventlet.spawn(foo)
{% endif %}


{#
# {% for event, functions in subscriptions.items() %}
# @socketio.on({{ event }})
# def _(*args):
#     {% for func in functions %}
#     foo = copy_current_request_context({{ source_module }}.{{ func }})
#     eventlet.spawn(foo, *(msgpack.unpackb(bytes(a['data']), encoding='utf8') for a in args))
#     {% endfor %}
# {% endfor %}
    #}

{# {% for event, (events, functions) in subscriptions.items() %} #}
{% for event, supports in subscriptions.items() %}
@socketio.on('{{ event[0] }}')
def _(*args):
    def wrapuser():
        uniq_events = set()
        {% for support in supports %}
        uniq_events.update({{ support[0] }})
        {% endfor %}
        uniq_events.remove({{ event }})
        {% set post = event[2] %}
        event_data = {}
        for ev in uniq_events:
            comp = getattr({{ source_module }}, ev[1])
            if ev[2] is None:
                ename = ev[0]
                raise GetterNotDefined('{ctype} has no getter associated with event "on_{ename}"'
                                       .format(ctype=type(comp), ename=ename[ename.find('#') + 1:]))
            getter = getattr(comp, ev[2])
            event_data[ev[0]] = getter()

        {% if post is not none %}
        event_data['{{ event[0] }}'] = {{ source_module }}.{{event[1]}}.{{ '_' ~ post }}(
            msgpack.unpackb(bytes(args[0]['data']), encoding='utf8')
        )
        {% endif %}

        {% for support in supports %}
            {% if post is not none %}
        user_args = []
                {% for ev in support[0] %}
        user_args.append(event_data['{{ ev[0] }}'])
                {% endfor %}
            {% endif %}
        {{ source_module }}.{{ support[1] }}(*user_args)
        {% endfor %}

    foo = copy_current_request_context(wrapuser)
    eventlet.spawn(foo)

{% endfor %}

@click.command()
@click.option('--host', '-h', default={{host}}, help='Host IP')
@click.option('--port', '-p', default={{port}}, help='port number')
def main(host, port):
    scheds = []
    {% for schedule in schedules %}
    sched = Scheduler({{ schedule.seconds }},
                      {{ source_module }}.{{ schedule.function }})
    scheds.append(sched)
    {% endfor %}

    for sched in scheds:
        sched.start()
    socketio.run(app, host=host, port=port)
    for sched in scheds:
        sched.stop()

if __name__ == '__main__':
    main()
