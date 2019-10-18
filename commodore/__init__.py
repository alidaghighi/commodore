#!/usr/bin/env python

import json, requests, os
from git import Repo
from url_normalize import url_normalize

def fetch_inventory(customer, cluster):
    r = requests.get(url_normalize(f"{API_URL}/inventory/{customer}/{cluster}"))
    resp = json.loads(r.text)
    if r.status_code == 404:
        print(resp['message'])
        return {}
    else:
        return resp

def fetch_git_repository(repository_url, directory):
    Repo.clone_from(url_normalize(repository_url), directory)

def fetch_config(response):
    config = response['global']['config']
    print(f"Updating global config...")
    fetch_git_repository(f"{GLOBAL_GIT_BASE}/{config}.git", f"inventory/classes/global")

def fetch_component(component):
    repository_url = f"{GLOBAL_GIT_BASE}/components/{component}.git"
    target_directory = f"dependencies/{component}"
    fetch_git_repository(repository_url, target_directory)
    os.symlink(os.path.abspath(f"{target_directory}/class/{component}.yml"), f"inventory/classes/components/{component}.yml")

def fetch_components(response):
    components = response['global']['components']
    os.makedirs('inventory/classes/components', exist_ok=True)
    for c in components:
        print(f"Updating component {c}...")
        fetch_component(c)

def fetch_target(customer, cluster):
    r = requests.get(url_normalize(f"{API_URL}/targets/{customer}/{cluster}"))
    resp = json.loads(r.text)
    if r.status_code == 404:
        print(resp['message'])
        return {}
    else:
        return resp

def fetch_customer_config(repo, customer):
    if repo is None:
        repo = f"{CUSTOMER_GIT_BASE}/{customer}.git"
    print("Updating customer config...")
    fetch_git_repository(repo, f"inventory/classes/{customer}")

def clean():
    import shutil
    shutil.rmtree("inventory", ignore_errors=True)
    shutil.rmtree("dependencies", ignore_errors=True)
    shutil.rmtree("compiled", ignore_errors=True)

def kapitan_compile():
    # TODO: maybe use kapitan.targets.compile_targets directly?
    import shlex, subprocess
    subprocess.run(shlex.split("kapitan compile"))

def compile(customer, cluster):
    clean()

    r = fetch_inventory(customer, cluster)

    # Fetch all Git repos
    fetch_config(r)
    fetch_components(r)
    fetch_customer_config(r['cluster'].get('override', None), customer)

    target = fetch_target(customer, cluster)
    os.makedirs('inventory/targets', exist_ok=True)
    with open(f"inventory/targets/{target['target']}.yml", 'w') as tgt:
        json.dump(target['contents'], tgt)

    kapitan_compile()

def main():
    import argparse, sys

    parser = argparse.ArgumentParser(description='Collate Kapitan inventory and compile targets')
    cmd = parser.add_subparsers(help='commands')
    compile_parser = cmd.add_parser('compile', help='compile catalog')
    compile_parser.add_argument("customer", help="customer for whom to compile catalog")
    compile_parser.add_argument("cluster", help="cluster for which to compile catalog")

    clean_parser = cmd.add_parser('clean', help='clean dynamic downloads')

    args = parser.parse_args()

    try:
        cmd = sys.argv[1]
    except IndexError:
        parser.print_help()
        sys.exit(1)

    global API_URL, GLOBAL_GIT_BASE, CUSTOMER_GIT_BASE
    API_URL=os.environ['API_URL']
    GLOBAL_GIT_BASE=os.environ['GLOBAL_GIT_BASE']
    CUSTOMER_GIT_BASE=os.environ['CUSTOMER_GIT_BASE']

    if cmd == 'compile':
        compile(args.customer, args.cluster)
    elif cmd == 'clean':
        clean()

if __name__ == "__main__":
    main()
