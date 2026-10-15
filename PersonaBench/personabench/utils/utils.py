import os
import json
import random
import logging
import numpy as np
from faker import Faker


def setup_logger(verbose):
    """Configure logger.

    Always emit at INFO so the per-benchmark log captures httpx's per-request
    lines (matches HERB / MCPEval / MCP-Universe / UserBench). The previous
    behavior silenced everything when verbose=False and explicitly filtered
    out 'HTTP Request' messages even when verbose=True, which made it
    impossible to audit which gateway the tested model was actually hitting.
    The ``verbose`` parameter is kept for call-site compatibility; toggling
    it now only swaps INFO vs DEBUG verbosity.
    """
    logger = logging.getLogger()
    logger.handlers.clear()
    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
    logger.addHandler(handler)
    # Surface httpx's per-request URL+status; httpcore stays at WARNING so we
    # don't drown the log in low-level connection-pool noise.
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.WARNING)




def save_json(data, file_path):
    with open(file_path, "w") as f:
        if isinstance(data, dict) or isinstance(data, list):
            json.dump(data, f, indent=4)
        elif isinstance(data, str):
            try:
                # Verify if it's a valid JSON string
                json.loads(data)
                f.write(data)
            except json.JSONDecodeError:
                raise ValueError("Provided string is not valid JSON")
        else:
            raise TypeError("Data must be a list/dictionary or a JSON string")


def load_json(file_path):
    with open(file_path, 'r') as f:
        data = json.load(f)
    return data


def set_random_seed(seed):
    """
    seed (int): The seed value to set for random number generators.
    """
    logging.info(f"Set random seed to {seed}")
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)  # if using multiple GPUs
            torch.backends.cudnn.deterministic = True
            torch.backends.cudnn.benchmark = False
    except ImportError:
        pass
    Faker.seed(seed)
    return True


def get_api_key(args):
    """Retrieve the API key from args or environment variable."""
    api_key = args.api_key if args.api_key else os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Please set the OpenAI API key either in args or by setting the OPENAI_API_KEY environment variable.")
    return api_key


def remove_key(json_data, key_to_remove):
    if isinstance(json_data, dict):
        return {k: remove_key(v, key_to_remove) for k, v in json_data.items() if k != key_to_remove}
    elif isinstance(json_data, list):
        return [remove_key(item, key_to_remove) for item in json_data]
    else:
        return json_data


def convert_json_to_plain_text(json_data, exclude=None):
    """
    conver json data to plain text for RAG
    exclude: the keys that should not be included
    """
    
    for key_to_remove in exclude:
        json_data = remove_key(json_data, key_to_remove)
    plian_text = json.dumps(json_data, separators=(',', ':'))
    return plian_text