#!/usr/bin/env python3
import os
import sys

# Change to workshop-bot directory
os.chdir('workshop-botzip/workshop-bot')
sys.path.insert(0, os.getcwd())

# Import and run the Flask app
from webapp import app

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
