import subprocess

setup_command = ["uv", "run", "./src/setup_server.py"]
subprocess.call(setup_command)