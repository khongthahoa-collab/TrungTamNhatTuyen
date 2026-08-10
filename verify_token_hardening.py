#!/usr/bin/env python3
# ==============================================================================
# ETHICAL HACKING DISCLAIMER:
# Script này CHỈ được sử dụng trên môi trường DEV LOCAL cá nhân.
# ==============================================================================
"""Kiểm thử nhanh việc hardening Bearer token trên /api/v1: header thiếu/sai
định dạng bị từ chối đúng envelope api_error, và token hợp lệ vẫn được chấp
nhận bình thường.

Usage:
    python3 verify_token_hardening.py -u http://localhost:5000 -t <token>
"""
import requests
import argparse
from colorama import Fore, init

init(autoreset=True)


def verify_token_hardening(base_url, test_token):
    endpoint = f"{base_url.rstrip('/')}/api/v1/classes"

    print(f"[*] Testing Endpoint: {endpoint}")

    # Case 1: Malformed Bearer Header
    h1 = {"Authorization": "Bearer"}
    r1 = requests.get(endpoint, headers=h1)
    if r1.status_code == 401 and "error" in r1.json():
        print(f"{Fore.GREEN}[OK] PASS: Malformed header rejected with standard api_error envelope (401).")
    else:
        print(f"{Fore.RED}[!] FAIL: Status {r1.status_code} - Response: {r1.text}")

    # Case 2: Missing Authorization header entirely
    r_missing = requests.get(endpoint)
    if r_missing.status_code == 401 and "error" in r_missing.json():
        print(f"{Fore.GREEN}[OK] PASS: Missing header rejected with standard api_error envelope (401).")
    else:
        print(f"{Fore.RED}[!] FAIL: Status {r_missing.status_code} - Response: {r_missing.text}")

    # Case 3: Garbage token
    h3 = {"Authorization": "Bearer not-a-real-token"}
    r3 = requests.get(endpoint, headers=h3)
    if r3.status_code == 401 and r3.json().get('error', {}).get('code') == 'unauthorized':
        print(f"{Fore.GREEN}[OK] PASS: Invalid token rejected with code=unauthorized (401).")
    else:
        print(f"{Fore.RED}[!] FAIL: Status {r3.status_code} - Response: {r3.text}")

    # Case 4: Valid token check
    h4 = {"Authorization": f"Bearer {test_token}"}
    r4 = requests.get(endpoint, headers=h4)
    if r4.status_code == 200:
        print(f"{Fore.GREEN}[OK] PASS: Valid token accepted.")
    elif r4.status_code == 401:
        code = r4.json().get('error', {}).get('code')
        print(f"{Fore.YELLOW}[-] Token rejected (code={code}) - expired or invalid, check the token you passed.")
    else:
        print(f"{Fore.RED}[!] FAIL: Unexpected status {r4.status_code} - Response: {r4.text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--url", required=True, help="Base URL (e.g. http://localhost:5000)")
    parser.add_argument("-t", "--token", required=True, help="Test Bearer Token")
    args = parser.parse_args()

    verify_token_hardening(args.url, args.token)
