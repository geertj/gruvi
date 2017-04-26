# HTTP client and server example.

from gruvi.http import HttpClient, HttpServer

def handler(env, start_response):
    headers = [('Content-Type', 'text/plain; charset=UTF-8')]
    status = '200 OK'
    body = 'pong'
    start_response(status, headers)
    yield body.encode('utf-8')

server = HttpServer(handler)
server.listen(('localhost', 0))
addr = server.addresses[0]

client = HttpClient()
client.connect(addr)
client.request('GET', '/ping')

resp = client.getresponse()
assert resp.status_code == 200

body = resp.body.read()
print('result = {}'.format(body.decode(resp.charset)))
