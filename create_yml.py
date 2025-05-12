import sys
from copy import deepcopy
from ruamel.yaml import YAML

def main(template_key: str, count: int, infile: str, outfile: str):
    yaml = YAML()
    with open(infile) as f:
        data = yaml.load(f)  # type: dict

    services = data.get('services', {})
    if template_key not in services:
        print(f"Error: service '{template_key}' not found in {infile}", file=sys.stderr)
        sys.exit(1)

    # Extract and remove template
    template = services.pop(template_key)
    
    # Generate numbered services
    for i in range(1, count+1):
        name = f"{template_key}-{i}"
        svc = deepcopy(template)

        # Set UAV_ID in environment
        env = svc.get('environment', {})
        env['UAV_ID'] = str(i).zfill(2)
        svc['environment'] = env

        # Force single replica
        deploy = svc.get('deploy', {})
        deploy['replicas'] = 1
        svc['deploy'] = deploy

        services[name] = svc

    data['services'] = services

    # Write out new file
    with open(outfile, 'w') as f:
        yaml.dump(data, f)

if __name__ == '__main__':
    if len(sys.argv) != 5:
        print("Usage: generate_compose.py TEMPLATE_KEY COUNT INFILE OUTFILE", file=sys.stderr)
        sys.exit(1)
    _, tmpl, cnt, inp, out = sys.argv
    main(tmpl, int(cnt), inp, out)
