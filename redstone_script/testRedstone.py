import subprocess
import json
from app.liquidation.utils import create_contract_instance, load_config

config = load_config()

def call_node_script(feed_ids):
    feed_ids_json = json.dumps(feed_ids)
    print("Feed IDs JSON:", feed_ids_json)

    result = subprocess.run(
        ["node", "getRedstonePayload.js", feed_ids_json],
        capture_output=True,
        text=True,
        check=True
    )

    if result.returncode != 0:
        print("Error running script:", result.stderr)
        return None

    print("Script stdout:", result.stdout)
    print("Script stderr:", result.stderr)

    if not result.stdout:
        print("No output from script")
        return None

    output = json.loads(result.stdout)

    return output

def get_feed_ids(oracle_addresses):
    feed_ids = []
    for oracle_address in oracle_addresses:
        oracle = create_contract_instance(oracle_address, config.ORACLE_ABI_PATH)

        feed_id = '0x' + oracle.functions.feedId().call().hex()
        feed_ids.append(feed_id)
    return feed_ids

oracle_addresses = ["0xdfe70cD7FB6BbD9a519494eD6595A2a9AfAffCBF", "0x5B447ba6B204A8efDcc5b8f9FDf7361F332dC090"]
feed_ids = get_feed_ids(oracle_addresses)

print("Feed IDs: ", feed_ids)

processed_data = call_node_script(feed_ids)

print("Processed data: ", processed_data)

for data in processed_data:
    print("Stripped payload: ", data['data'])
