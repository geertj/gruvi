from flask import Flask, request, send_from_directory

app = Flask(__name__)

@app.route('/<path:name>')
def send_static(name):
    return send_from_directory('_build/html', name)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port='8080')
