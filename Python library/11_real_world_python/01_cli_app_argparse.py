"""
Topic: CLI App (argparse)
Goal: Build command-line tools
"""

import argparse

parser = argparse.ArgumentParser()

parser.add_argument("--name", type=str, required=True)
parser.add_argument("--age", type=int)

args = parser.parse_args()

print(f"Name: {args.name}")
print(f"Age: {args.age}")

#python script.py --name Alice --age 25