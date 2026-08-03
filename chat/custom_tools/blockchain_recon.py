"""Blockchain Recon Tool - Investigate wallets, transactions, and protocols."""

import json
import subprocess
from pathlib import Path
from datetime import datetime

RECON_LOG = Path(__file__).parent / "skill_data" / "blockchain_recon.json"

def get_tool_schema():
    return {
        "type": "function",
        "function": {
            "name": "blockchain_recon",
            "description": "Blockchain investigation tool. Actions: wallet, transactions, token, protocol, whale, approve, revoke.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["wallet", "transactions", "token", "protocol", "whale", "approve", "revoke"]},
                    "target": {"type": "string", "description": "Wallet address, tx hash, or token address"},
                    "chain": {"type": "string", "description": "Blockchain network"},
                    "options": {"type": "string", "description": "Additional options"}
                },
                "required": ["action", "target"]
            }
        }
    }

RPC_ENDPOINTS = {
    "ethereum": "https://eth.llamarpc.com",
    "polygon": "https://polygon-rpc.com",
    "bsc": "https://bsc-dataseed.binance.org",
    "arbitrum": "https://arb1.arbitrum.io/rpc"
}

def _cmd(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"stdout": r.stdout[:10000], "stderr": r.stderr[:3000], "code": r.returncode}
    except Exception as e:
        return {"error": str(e)}

def _log(action, target, chain):
    RECON_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = json.loads(RECON_LOG.read_text()) if RECON_LOG.exists() else []
    log.append({"timestamp": datetime.now().isoformat(), "action": action, "target": target, "chain": chain})
    RECON_LOG.write_text(json.dumps(log, indent=2))

def run(action, target, chain="ethereum", options="{}"):
    rpc = RPC_ENDPOINTS.get(chain, RPC_ENDPOINTS["ethereum"])

    if action == "wallet":
        balance = _cmd(f"cast balance {target} --rpc-url {rpc} 2>/dev/null")
        eth_balance = _cmd(f"cast balance {target} --rpc-url {rpc} --ether 2>/dev/null")
        nonce = _cmd(f"cast nonce {target} --rpc-url {rpc} 2>/dev/null")
        
        code = _cmd(f"cast code {target} --rpc-url {rpc} 2>/dev/null")
        is_contract = "0x" in code.get("stdout", "") and len(code.get("stdout", "")) > 2
        
        _log("wallet", target, chain)
        return json.dumps({
            "action": "wallet",
            "address": target,
            "chain": chain,
            "balance_wei": balance.get("stdout", "").strip(),
            "balance_eth": eth_balance.get("stdout", "").strip(),
            "nonce": nonce.get("stdout", "").strip(),
            "is_contract": is_contract,
            "explorer": f"https://{chain}.etherscan.io/address/{target}"
        })

    elif action == "transactions":
        txs = _cmd(f"cast tx {target} --rpc-url {rpc} 2>/dev/null")
        receipt = _cmd(f"cast receipt {target} --rpc-url {rpc} 2>/dev/null")
        
        _log("transactions", target, chain)
        return json.dumps({
            "action": "transactions",
            "tx_hash": target,
            "chain": chain,
            "transaction": txs.get("stdout", ""),
            "receipt": receipt.get("stdout", ""),
            "explorer": f"https://{chain}.etherscan.io/tx/{target}"
        })

    elif action == "token":
        name = _cmd(f"cast call {target} 'name()(string)' --rpc-url {rpc} 2>/dev/null")
        symbol = _cmd(f"cast call {target} 'symbol()(string)' --rpc-url {rpc} 2>/dev/null")
        decimals = _cmd(f"cast call {target} 'decimals()(uint8)' --rpc-url {rpc} 2>/dev/null")
        total_supply = _cmd(f"cast call {target} 'totalSupply()(uint256)' --rpc-url {rpc} 2>/dev/null")
        
        _log("token", target, chain)
        return json.dumps({
            "action": "token",
            "address": target,
            "chain": chain,
            "name": name.get("stdout", "").strip(),
            "symbol": symbol.get("stdout", "").strip(),
            "decimals": decimals.get("stdout", "").strip(),
            "total_supply": total_supply.get("stdout", "").strip(),
            "explorer": f"https://{chain}.etherscan.io/token/{target}"
        })

    elif action == "protocol":
        _log("protocol", target, chain)
        protocols = {
            "uniswap": {"type": "DEX", "contracts": ["Factory", "Router", "Pool"]},
            "aave": {"type": "Lending", "contracts": ["Pool", "LendingPool", "Oracle"]},
            "compound": {"type": "Lending", "contracts": ["Comptroller", "CErc20"]},
            "curve": {"type": "DEX", "contracts": ["Factory", "Pool"]},
            "sushiswap": {"type": "DEX", "contracts": ["Factory", "Router"]}
        }
        info = protocols.get(target.lower(), {"type": "Unknown", "contracts": []})
        return json.dumps({
            "action": "protocol",
            "name": target,
            "type": info["type"],
            "contracts": info["contracts"],
            "attack_vectors": ["Flash loan", "Oracle manipulation", "Governance attack", "Liquidity drain"]
        })

    elif action == "whale":
        eth_bal = _cmd(f"cast balance {target} --rpc-url {rpc} --ether 2>/dev/null")
        balance = float(eth_bal.get("stdout", "0").strip() or "0")
        
        _log("whale", target, chain)
        classification = "MEGAWHALE" if balance > 10000 else "WHALE" if balance > 1000 else "SHARK" if balance > 100 else "FISH"
        
        return json.dumps({
            "action": "whale",
            "address": target,
            "chain": chain,
            "balance_eth": balance,
            "classification": classification,
            "monitoring": f"Track this address for large movements"
        })

    elif action == "approve":
        spender = input("Enter spender address: ") if options == "{}" else json.loads(options).get("spender", "")
        amount = input("Enter amount (uint256 max for unlimited): ") if options == "{}" else json.loads(options).get("amount", "115792089237316195423570985008687907853269984665640564039457584007913129639935")
        
        tx_data = _cmd(f"cast calldata 'approve(address,uint256)' {spender} {amount} 2>/dev/null")
        
        _log("approve", target, chain)
        return json.dumps({
            "action": "approve",
            "token": target,
            "spender": spender,
            "amount": amount,
            "calldata": tx_data.get("stdout", ""),
            "warning": "This grants the spender access to your tokens"
        })

    elif action == "revoke":
        spender = json.loads(options).get("spender", "")
        if not spender:
            return json.dumps({"error": "spender address required in options"})
        
        tx_data = _cmd(f"cast calldata 'approve(address,uint256)' {spender} 0 2>/dev/null")
        
        _log("revoke", target, chain)
        return json.dumps({
            "action": "revoke",
            "token": target,
            "spender": spender,
            "calldata": tx_data.get("stdout", ""),
            "note": "Sets allowance to 0, revoking access"
        })

    return json.dumps({"error": f"Unknown action: {action}"})


if __name__ == "__main__":
    print(run("wallet", "0x0000000000000000000000000000000000000000"))
