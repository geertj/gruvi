# Gruvi example program: a "fortune" web service

import locale
import gruvi
import contextlib

def fortune_app(environ, start_response):
    print('New connection from {0}'.format(environ['REMOTE_ADDR']))
    proc = gruvi.Process(encoding=locale.getpreferredencoding())
    proc.spawn('fortune', stdout=gruvi.PIPE)
    with contextlib.closing(proc):
        fortune = proc.stdout.read()
        proc.wait()
    start_response('200 OK', [('Content-Type', 'text/plain; charset=utf-8')])
    return [fortune.encode('utf-8')]

server = gruvi.HttpServer(fortune_app)
server.listen(('localhost', 0))
for addr in server.addresses:
    print('Listen on {0}'.format(gruvi.saddr(addr)))

server.run()
