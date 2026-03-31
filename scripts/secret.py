#!/usr/bin/env python3
"""
Minimal helper to add a GEMINI_API_KEY secret version and attach it to a Cloud Run service.

Usage:
  # Interactive (recommended): will prompt you to paste the key (hidden)
  python scripts/secret.py --service applydi-backend --region europe-west1

  # Non-interactive (CI): provide key on stdin
  printf '%s' 'MY_KEY' | python scripts/secret.py --non-interactive --service applydi-backend --region europe-west1

Requirements:
  - gcloud CLI installed and authenticated
  - Caller has permissions to manage Secret Manager and Cloud Run

This script does:
  1. create secret GEMINI_API_KEY if it does not exist
  2. add a new secret version containing the provided key
  3. retrieve the Cloud Run service account for the given service
  4. grant roles/secretmanager.secretAccessor to that service account on the secret
  5. update the Cloud Run service to attach the secret as env var GEMINI_API_KEY
"""

import argparse
import getpass
import shutil
import subprocess
import sys
import os


def shell(cmd, input_bytes=None, check=True, capture_output=False):
    """Run command (list) and return CompletedProcess.

    On Windows the gcloud entrypoint may be a batch file; some environments
    need shell=True to execute it correctly. We detect Windows and run via
    the shell there. For Unix we run directly.
    """
    is_windows = os.name == 'nt'
    if is_windows:
        # convert list to command line string safely
        cmd_str = subprocess.list2cmdline(cmd)
        run_kwargs = {"shell": True}
        if capture_output:
            run_kwargs.update({"stdout": subprocess.PIPE, "stderr": subprocess.PIPE})
        if input_bytes is not None:
            proc = subprocess.run(cmd_str, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        else:
            proc = subprocess.run(cmd_str, **run_kwargs)
    else:
        run_kwargs = {"shell": False}
        if capture_output:
            run_kwargs.update({"stdout": subprocess.PIPE, "stderr": subprocess.PIPE})
        if input_bytes is not None:
            proc = subprocess.run(cmd, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            proc = subprocess.run(cmd, **run_kwargs)

    if check and proc.returncode != 0:
        if capture_output and (proc.stdout or proc.stderr):
            out = proc.stdout.decode(errors='ignore') if proc.stdout else ''
            err = proc.stderr.decode(errors='ignore') if proc.stderr else ''
            print(f"Command failed: {cmd if not is_windows else cmd_str}\nstdout:\n{out}\nstderr:\n{err}")
        else:
            print(f"Command failed: {cmd if not is_windows else cmd_str} (exit {proc.returncode})")
        sys.exit(proc.returncode)
    return proc


def ensure_gcloud():
    if shutil.which('gcloud') is None:
        print('gcloud not found in PATH. Install Google Cloud SDK before running.')
        sys.exit(1)


def secret_exists(project: str) -> bool:
    # use shell helper to be consistent across platforms
    proc = shell(['gcloud', 'secrets', 'describe', 'GEMINI_API_KEY', '--project', project], capture_output=True, check=False)
    return proc.returncode == 0


def main():
    ensure_gcloud()

    p = argparse.ArgumentParser()
    p.add_argument('--project', default='applydi', help='GCP project id')
    p.add_argument('--service', default='applydi-backend', help='Cloud Run service name')
    p.add_argument('--region', default='europe-west1', help='Cloud Run region')
    p.add_argument('--non-interactive', action='store_true', help='Read key from stdin')
    args = p.parse_args()

    project = args.project
    service = args.service
    region = args.region

    # 1) create secret if needed
    if not secret_exists(project):
        print('Creating secret GEMINI_API_KEY...')
        shell(['gcloud', 'secrets', 'create', 'GEMINI_API_KEY', '--replication-policy=automatic', '--project', project], check=False)
    else:
        print('Secret exists; will add a new version.')

    # 2) read key
    if args.non_interactive:
        key = sys.stdin.buffer.read()
        if not key:
            print('No key provided on stdin for non-interactive mode')
            sys.exit(2)
        key = key.rstrip(b'\n\r')
        input_bytes = key
    else:
        secret_text = getpass.getpass('Paste GEMINI API key (hidden input): ')
        input_bytes = secret_text.encode('utf-8')

    # 3) add secret version
    print('Adding secret version...')
    shell(['gcloud', 'secrets', 'versions', 'add', 'GEMINI_API_KEY', '--data-file=-', '--project', project], input_bytes=input_bytes)
    print('Secret version added.')

    # 4) get cloud run service account
    print(f'Retrieving Cloud Run service account for {service} in {region}...')
    proc = shell(['gcloud', 'run', 'services', 'describe', service, '--platform=managed', '--region', region, '--project', project, '--format=value(spec.template.spec.serviceAccountName)'], capture_output=True, check=False)
    sa = ''
    if proc.returncode == 0 and proc.stdout:
        sa = proc.stdout.decode().strip()
    if not sa:
        print('Failed to get Cloud Run service account. Check service name, region and authentication.')
        sys.exit(3)
    if '@' not in sa:
        sa = f'{sa}@{project}.iam.gserviceaccount.com'
    print(f'Using service account: {sa}')

    # 5) grant secret accessor
    print('Granting secretAccessor role to the service account...')
    shell(['gcloud', 'secrets', 'add-iam-policy-binding', 'GEMINI_API_KEY', '--project', project, '--member', f'serviceAccount:{sa}', '--role', 'roles/secretmanager.secretAccessor'])

    # 6) attach secret to cloud run
    print('Updating Cloud Run service to attach secret as GEMINI_API_KEY...')
    shell(['gcloud', 'run', 'services', 'update', service, '--project', project, '--region', region, '--update-secrets', 'GEMINI_API_KEY=GEMINI_API_KEY:latest'])

    print('Done. GEMINI_API_KEY is attached to the Cloud Run service.')


if __name__ == '__main__':
    main()
