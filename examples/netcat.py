# Gruvi example program: a nc(1) like client, using StreamClient

import sys
import argparse
import gruvi

parser = argparse.ArgumentParser()
parser.add_argument('hostname')
parser.add_argument('port', type=int)
parser.add_argument('--ssl', action='store_true')
args = parser.parse_args()

remote = gruvi.StreamClient()
remote.connect((args.hostname, args.port), ssl=args.ssl)

stdin = gruvi.StreamClient()
stdin.connect(sys.stdin.fileno(), mode='r')
stdout = gruvi.StreamClient()
stdout.connect(sys.stdout.fileno(), mode='w')

done = gruvi.Event()

def stdin_reader():
    while True:
        buf = stdin.read1()
        if not buf:
            print('Got EOF on stdin')
            break
        remote.write(buf)
    done.set()

def remote_reader():
    while True:
        buf = remote.read1()
        if not buf:
            print('Got EOF from remote')
            break
        stdout.write(buf)
    done.set()

gruvi.spawn(stdin_reader)
gruvi.spawn(remote_reader)

done.wait()
