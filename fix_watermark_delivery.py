#!/usr/bin/env python3
"""
Fix n8n_post_content.json to restore watermark delivery chain
"""
import json
from collections import Counter

def main():
    # Load the JSON file
    with open('n8n_post_content.json', 'r') as f:
        data = json.load(f)

    nodes = data['nodes']
    node_names = [n['name'] for n in nodes]

    # Check for duplicates
    duplicates = [name for name, count in Counter(node_names).items() if count > 1]
    if duplicates:
        print(f"ERROR: Duplicate node names: {duplicates}")
        return False

    # Check required nodes exist
    required_nodes = {
        'If Watermark Completed2',
        'Get Watermark Result',
        'Prepare Telegram Payload',
        'Send a text message',
        'Download Watermark Video',
        'Send a video',
    }
    missing = required_nodes - set(node_names)
    if missing:
        print(f"ERROR: Missing nodes: {missing}")
        return False

    # Check connections
    connections = data.get('connections', {})

    def get_targets(source):
        result = []
        for group in connections.get(source, {}).get('main', []):
            result.extend(edge['node'] for edge in group)
        return result

    checks = {
        'If Watermark Completed2': ['Get Watermark Result', 'Wait Watermark2'],
        'Get Watermark Result': ['Prepare Telegram Payload'],
        'Prepare Telegram Payload': ['Send a text message', 'Download Watermark Video'],
        'Download Watermark Video': ['Send a video'],
    }

    for source, expected in checks.items():
        actual = get_targets(source)
        for exp in expected:
            if exp not in actual:
                print(f"ERROR: {source} must connect to {exp}; actual={actual}")
                return False

    print("OK: All validations passed!")
    print("- No duplicate node names")
    print("- No broken connections")
    print("- Final watermark delivery chain restored")
    return True

if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
