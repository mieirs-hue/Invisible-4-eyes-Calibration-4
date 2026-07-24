import yaml

def load_config(path="config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)


def save_config(config, path="config.yaml"):
    with open(path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)