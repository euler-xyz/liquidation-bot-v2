import requests
from typing import TypedDict
from eth_utils import to_checksum_address

class SwapResponse(TypedDict):
    swapperAddress: str
    swapperData: str
    multicallItems: list

def get_swap_quote(
    chain_id: int,
    token_in: str, 
    token_out: str,
    amount: int, # exact in - amount to sell, exact out - amount to buy, exact out repay - estimated amount to buy (from current debt)
    min_amount_out: int,
    receiver: str, # vault to swap or repay to
    vault_in: str,
    origin: str,
    account_in: str,
    account_out: str,
    swapper_mode: str,
    slippage: float, #in percent 1 = 1%
    deadline: int,
    is_repay: bool,
    current_debt: int, # needed in exact input or output and with `isRepay` set
    target_debt: int # ignored if not in target debt mode
) -> SwapResponse:
    # Normalize addresses
    token_in = to_checksum_address(token_in)
    token_out = to_checksum_address(token_out)
    receiver = to_checksum_address(receiver)
    vault_in = to_checksum_address(vault_in)
    origin = to_checksum_address(origin)
    account_in = to_checksum_address(account_in)
    account_out = to_checksum_address(account_out)

    params = {
        "chainId": str(chain_id),
        "tokenIn": token_in,
        "tokenOut": token_out, 
        "amount": str(amount),
        "receiver": receiver,
        "vaultIn": vault_in,
        "origin": origin,
        "accountIn": account_in,
        "accountOut": account_out,
        "swapperMode": swapper_mode,  # TARGET_DEBT mode
        "slippage": str(slippage),
        "deadline": str(deadline),  # 30 min
        "isRepay": str(is_repay),
        "currentDebt": str(current_debt),  # 2000 USDC debt
        "targetDebt": str(target_debt)  # Fully repay the debt
    }

    response = requests.get("http://localhost:3002/swap", params=params)
    
    if not response.ok:
        raise Exception(f"Request failed: {response.status_code} {response.text}")
        
    data = response.json()
    
    if not data["success"]:
        raise Exception(f"Swap failed: {data['message']}")
        
    amount_out = int(data["data"]["amountOut"])
    if amount_out < min_amount_out:
        raise ValueError(
            f"Quote too low: got {amount_out}, wanted minimum {min_amount_out}"
        )
        
    return data["data"]

# Example usage
if __name__ == "__main__":
    IN_VAULT = "0x631D8E808f2c4177a8147Eaa39a4F57C47634dE8"
    LIQUIDATOR_EOA = "0x8cbB534874bab83e44a7325973D2F04493359dF8" 
    BORROW_VAULT = "0xa992d3777282c44ee980e9b0ca9bd0c0e4f737af"
    
    try:
        swap_response = get_swap_quote(
            chain_id=1,
            token_in="0x8c9532a60E0E7C6BbD2B2c1303F63aCE1c3E9811",
            token_out="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  
            amount=int(.03518*10**18),
            # amount=int(.04061*10**18),
            min_amount_out=0,
            receiver=BORROW_VAULT,
            vault_in=IN_VAULT,
            origin=LIQUIDATOR_EOA,
            account_in=LIQUIDATOR_EOA,
            account_out=LIQUIDATOR_EOA,
            swapper_mode="0",
            slippage=1.0,
            deadline=600,
            is_repay=False,
            # current_debt=int(.04061*10**18),
            current_debt=0,
            target_debt=0
        )
        swap = swap_response['swap']
        print("\nSwap Response:")
        print("-------------")
        print(f"Amount In: {swap_response['amountIn']}")
        print(f"Max Amount In: {swap_response['amountInMax']}")
        print(f"Amount Out: {swap_response['amountOut']}")
        print(f"Min Amount Out: {swap_response['amountOutMin']}")
        print(f"\nAccounts:")
        print(f"  Account In: {swap_response['accountIn']}")
        print(f"  Account Out: {swap_response['accountOut']}")
        print(f"  Vault In: {swap_response['vaultIn']}")
        print(f"  Receiver: {swap_response['receiver']}")
        print(f"\nTokens:")
        print(f"  Token In: {swap_response['tokenIn']['symbol']} ({swap_response['tokenIn']['addressInfo']})")
        print(f"    Name: {swap_response['tokenIn']['name']}")
        print(f"    Decimals: {swap_response['tokenIn']['decimals']}")
        print(f"  Token Out: {swap_response['tokenOut']['symbol']} ({swap_response['tokenOut']['addressInfo']})")
        print(f"    Name: {swap_response['tokenOut']['name']}")
        print(f"    Decimals: {swap_response['tokenOut']['decimals']}")
        print(f"\nSlippage: {swap_response['slippage']}%")
        print(f"\nRoute:")
        for step in swap_response['route']:
            print(f"  - {step['providerName']}")
            
        print("\nMulticall Items:")
        print("---------------")
        for i, item in enumerate(swap['multicallItems'], 1):
            print(f"\nStep {i}:")
            print(f"  Function: {item['functionName']}")
            print(f"  Arguments: {item['args']}")
            print(f" Call data: {item['data']}")
        
        swap_data = []
        for _, item in enumerate(swap['multicallItems']):
            swap_data.append(item['data'])

        print(swap_data)

    except ValueError as e:
        print(f"Quote check failed: {e}")
    except Exception as e:
        print(f"Request failed: {e}")