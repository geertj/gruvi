# Ping-pong between JSON-RPC client and server.

from gruvi.jsonrpc import JsonRpcClient, JsonRpcServer

def handler(message, transport, protocol):
    method = message.get('method')
    if method == 'ping':
        protocol.send_response(message, 'pong')

server = JsonRpcServer(handler)
server.listen(('localhost', 0))
addr = server.addresses[0]

client = JsonRpcClient()
client.connect(addr)
result = client.call_method('ping')

print('result = {}'.format(result))
