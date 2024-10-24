import json

def load_data(path):
    with open(path, 'r') as file:
        data = json.load(file)
    return data
